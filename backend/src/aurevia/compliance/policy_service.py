"""Which policy version applies to a tenant, and the tenant's own stricter settings."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.compliance.models import PolicyVersion, TenantComplianceSettings
from aurevia.compliance.policy import (
    PolicyOverrides,
    PolicyPack,
    PolicyRules,
    PolicyStatus,
    apply_overrides,
    looser_overrides,
)
from aurevia.errors import AureviaError, NotFoundError, ServiceUnavailableError
from aurevia.identity.audit import record_audit_event


class LooserSettingsError(AureviaError):
    status_code = 422
    code = "settings_looser_than_policy"


def pack_of(version: PolicyVersion) -> PolicyPack:
    return PolicyPack.from_rules(
        name=version.pack,
        version=version.version,
        status=PolicyStatus(version.status),
        rules=PolicyRules.model_validate(version.rules),
        version_id=version.id,
    )


class PolicyService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def versions(self, pack: str) -> list[PolicyVersion]:
        rows = await self._session.scalars(
            select(PolicyVersion)
            .where(PolicyVersion.pack == pack)
            .order_by(PolicyVersion.created_at.desc())
        )
        return list(rows)

    async def settings(self) -> TenantComplianceSettings | None:
        return await self._session.scalar(
            select(TenantComplianceSettings).where(
                TenantComplianceSettings.tenant_id == self._tenant_id
            )
        )

    async def _default_version(self, pack: str) -> PolicyVersion | None:
        """The newest reviewed version, else the newest draft. Retired ones never apply."""
        for status in (PolicyStatus.REVIEWED, PolicyStatus.DRAFT):
            version = await self._session.scalar(
                select(PolicyVersion)
                .where(PolicyVersion.pack == pack, PolicyVersion.status == status)
                .order_by(PolicyVersion.created_at.desc())
                .limit(1)
            )
            if version is not None:
                return version
        return None

    async def _version_for(
        self, pack: str, settings: TenantComplianceSettings | None
    ) -> PolicyVersion:
        version = None
        if settings is not None and settings.policy_version_id is not None:
            pinned = await self._session.get(PolicyVersion, settings.policy_version_id)
            if pinned is not None and pinned.pack == pack and pinned.status != PolicyStatus.RETIRED:
                version = pinned
        version = version or await self._default_version(pack)
        if version is None:
            raise ServiceUnavailableError(f"No usable policy version for pack '{pack}'")
        return version

    async def effective_pack(self, pack: str) -> PolicyPack:
        settings = await self.settings()
        effective = pack_of(await self._version_for(pack, settings))
        if settings is not None and settings.overrides:
            effective = apply_overrides(
                effective, PolicyOverrides.model_validate(settings.overrides)
            )
        return effective

    async def update_settings(
        self,
        pack: str,
        *,
        policy_version_id: uuid.UUID | None,
        overrides: PolicyOverrides,
        actor: uuid.UUID,
    ) -> TenantComplianceSettings:
        if policy_version_id is not None:
            pinned = await self._session.get(PolicyVersion, policy_version_id)
            if pinned is None or pinned.pack != pack or pinned.status == PolicyStatus.RETIRED:
                raise NotFoundError("Policy version not found or retired")
        settings = await self.settings()
        candidate = TenantComplianceSettings(
            tenant_id=self._tenant_id, policy_version_id=policy_version_id
        )
        base = pack_of(await self._version_for(pack, candidate))
        looser = looser_overrides(base, overrides)
        if looser:
            raise LooserSettingsError(
                "Settings may only make the policy stricter", details={"fields": looser}
            )
        if settings is None:
            settings = candidate
            self._session.add(settings)
        settings.policy_version_id = policy_version_id
        settings.overrides = overrides.model_dump(mode="json", exclude_none=True)
        settings.updated_by_user_id = actor
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="compliance.settings_updated",
            target_type="tenant_compliance_settings",
            target_id=self._tenant_id,
            details={
                "policy_version_id": str(policy_version_id) if policy_version_id else None,
                "overrides": settings.overrides,
            },
        )
        await self._session.commit()
        return settings
