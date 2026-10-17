"""Playbook versions and entries (WP-12.7, 12.A). Every change is audited.

Only a draft changes. Activating a draft freezes it and retires the agent's previous active
version. An entry is used in calls only once a person has approved it and its version is
active (the retrieval side is WP-12.7's second part).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.playbooks.models import EntryStatus, PlaybookEntry, PlaybookStatus, PlaybookVersion
from aurevia.playbooks.schemas import EntryIn, VersionCreateIn
from aurevia.voice.models import Agent

SEED_FILE = Path(__file__).with_name("seed_entries.json")
MAX_ENTRIES = 200


def seed_entries() -> list[EntryIn]:
    """The built-in seed entries (WP-12.A), validated like any other entry."""
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    return [EntryIn.model_validate(entry) for entry in data["entries"]]


class NotADraftError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Only a draft playbook can change", code="playbook_not_draft")


class PlaybookService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def _agent(self, agent_id: uuid.UUID, *, lock: bool = False) -> Agent:
        query = select(Agent).where(Agent.id == agent_id, Agent.tenant_id == self._tenant_id)
        if lock:
            query = query.with_for_update()  # serialises version numbers and activation
        agent = await self._session.scalar(query)
        if agent is None:
            raise NotFoundError("Agent not found")
        return agent

    async def get_version(self, version_id: uuid.UUID, *, lock: bool = False) -> PlaybookVersion:
        query = select(PlaybookVersion).where(
            PlaybookVersion.id == version_id, PlaybookVersion.tenant_id == self._tenant_id
        )
        if lock:
            query = query.with_for_update()
        version = await self._session.scalar(query)
        if version is None:
            raise NotFoundError("Playbook not found")
        return version

    async def entries(self, version_id: uuid.UUID) -> list[PlaybookEntry]:
        rows = await self._session.scalars(
            select(PlaybookEntry)
            .where(
                PlaybookEntry.version_id == version_id,
                PlaybookEntry.tenant_id == self._tenant_id,
            )
            .order_by(PlaybookEntry.position)
        )
        return list(rows)

    async def list_versions(self, agent_id: uuid.UUID | None = None) -> list[PlaybookVersion]:
        query = select(PlaybookVersion).where(PlaybookVersion.tenant_id == self._tenant_id)
        if agent_id is not None:
            query = query.where(PlaybookVersion.agent_id == agent_id)
        rows = await self._session.scalars(
            query.order_by(PlaybookVersion.agent_id, PlaybookVersion.version.desc())
        )
        return list(rows)

    def _add_entry(
        self,
        version: PlaybookVersion,
        position: int,
        entry: EntryIn,
        *,
        status: EntryStatus = EntryStatus.PROPOSED,
        approved_by: uuid.UUID | None = None,
        approved_at: datetime | None = None,
    ) -> PlaybookEntry:
        row = PlaybookEntry(
            tenant_id=self._tenant_id,
            version_id=version.id,
            position=position,
            stage=entry.stage.value if entry.stage else None,
            situation=entry.situation,
            says=entry.says,
            tone=entry.tone,
            goal=entry.goal,
            source=entry.source,
            status=status.value,
            approved_by_user_id=approved_by,
            approved_at=approved_at,
        )
        self._session.add(row)
        return row

    async def create_version(
        self, body: VersionCreateIn, *, actor_user_id: uuid.UUID | None
    ) -> PlaybookVersion:
        if body.seed and body.copy_from_version_id is not None:
            raise ConflictError("Choose seed entries or a version to copy, not both")
        await self._agent(body.agent_id, lock=True)
        latest = await self._session.scalar(
            select(func.max(PlaybookVersion.version)).where(
                PlaybookVersion.tenant_id == self._tenant_id,
                PlaybookVersion.agent_id == body.agent_id,
            )
        )
        version = PlaybookVersion(
            tenant_id=self._tenant_id,
            agent_id=body.agent_id,
            version=(latest or 0) + 1,
            status=PlaybookStatus.DRAFT.value,
            notes=body.notes,
            created_by_user_id=actor_user_id,
        )
        self._session.add(version)
        await self._session.flush()
        copied = 0
        if body.seed:
            for position, entry in enumerate(seed_entries()):
                self._add_entry(version, position, entry)
            copied = len(seed_entries())
        elif body.copy_from_version_id is not None:
            source = await self.get_version(body.copy_from_version_id)
            if source.agent_id != body.agent_id:
                raise ConflictError("Copy only from a version of the same agent")
            for position, old in enumerate(await self.entries(source.id)):
                self._add_entry(
                    version,
                    position,
                    EntryIn.model_validate(old, from_attributes=True),
                    status=EntryStatus(old.status),
                    approved_by=old.approved_by_user_id,
                    approved_at=old.approved_at,
                )
                copied += 1
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action="playbook.version_created",
            actor_user_id=actor_user_id,
            target_type="playbook_version",
            target_id=version.id,
            details={
                "agent_id": str(body.agent_id),
                "version": version.version,
                "seed": body.seed,
                "copied_from": str(body.copy_from_version_id)
                if body.copy_from_version_id
                else None,
                "entries": copied,
            },
        )
        await self._session.commit()
        return version

    async def _draft(self, version_id: uuid.UUID) -> PlaybookVersion:
        version = await self.get_version(version_id, lock=True)
        if version.status != PlaybookStatus.DRAFT:
            raise NotADraftError
        return version

    async def _entry(self, version: PlaybookVersion, entry_id: uuid.UUID) -> PlaybookEntry:
        entry = await self._session.scalar(
            select(PlaybookEntry).where(
                PlaybookEntry.id == entry_id,
                PlaybookEntry.version_id == version.id,
                PlaybookEntry.tenant_id == self._tenant_id,
            )
        )
        if entry is None:
            raise NotFoundError("Playbook entry not found")
        return entry

    async def add_entry(
        self,
        version_id: uuid.UUID,
        body: EntryIn,
        *,
        actor_user_id: uuid.UUID | None,
        commit: bool = True,
    ) -> PlaybookEntry:
        version = await self._draft(version_id)
        existing = await self.entries(version.id)
        if len(existing) >= MAX_ENTRIES:
            raise ConflictError(f"A playbook holds at most {MAX_ENTRIES} entries")
        entry = self._add_entry(version, len(existing), body)
        await self._session.flush()
        self._audit("playbook.entry_added", entry, actor_user_id)
        if commit:
            await self._session.commit()
        return entry

    async def edit_entry(
        self,
        version_id: uuid.UUID,
        entry_id: uuid.UUID,
        body: EntryIn,
        *,
        actor_user_id: uuid.UUID | None,
    ) -> PlaybookEntry:
        """Change an entry in a draft. A changed entry goes back to proposed."""
        version = await self._draft(version_id)
        entry = await self._entry(version, entry_id)
        entry.stage = body.stage.value if body.stage else None
        entry.situation, entry.says, entry.tone = body.situation, body.says, body.tone
        entry.goal, entry.source = body.goal, body.source
        entry.status = EntryStatus.PROPOSED.value
        entry.approved_by_user_id = None
        entry.approved_at = None
        self._audit("playbook.entry_edited", entry, actor_user_id)
        await self._session.commit()
        return entry

    async def approve_entry(
        self, version_id: uuid.UUID, entry_id: uuid.UUID, *, actor_user_id: uuid.UUID | None
    ) -> PlaybookEntry:
        version = await self._draft(version_id)
        entry = await self._entry(version, entry_id)
        entry.status = EntryStatus.APPROVED.value
        entry.approved_by_user_id = actor_user_id
        entry.approved_at = datetime.now(UTC)
        self._audit("playbook.entry_approved", entry, actor_user_id)
        await self._session.commit()
        return entry

    async def activate(
        self, version_id: uuid.UUID, *, actor_user_id: uuid.UUID | None
    ) -> PlaybookVersion:
        """Freeze a draft as the agent's active playbook; the previous active one retires."""
        draft = await self.get_version(version_id)
        await self._agent(draft.agent_id, lock=True)
        version = await self._draft(version_id)
        approved = [e for e in await self.entries(version.id) if e.status == EntryStatus.APPROVED]
        if not approved:
            raise ConflictError(
                "Approve at least one entry before activating", code="playbook_not_approved"
            )
        now = datetime.now(UTC)
        previous = await self._session.scalar(
            select(PlaybookVersion)
            .where(
                PlaybookVersion.tenant_id == self._tenant_id,
                PlaybookVersion.agent_id == version.agent_id,
                PlaybookVersion.status == PlaybookStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        if previous is not None:
            previous.status = PlaybookStatus.RETIRED.value
            previous.retired_at = now
            await self._session.flush()  # free the one-active slot first
        version.status = PlaybookStatus.ACTIVE.value
        version.activated_at = now
        version.activated_by_user_id = actor_user_id
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action="playbook.version_activated",
            actor_user_id=actor_user_id,
            target_type="playbook_version",
            target_id=version.id,
            details={
                "agent_id": str(version.agent_id),
                "version": version.version,
                "approved_entries": len(approved),
                "retired_version_id": str(previous.id) if previous else None,
            },
        )
        await self._session.commit()
        return version

    async def retire(
        self, version_id: uuid.UUID, *, actor_user_id: uuid.UUID | None
    ) -> PlaybookVersion:
        """Retire a draft or the active version. With none active, no playbook is used."""
        version = await self.get_version(version_id, lock=True)
        if version.status == PlaybookStatus.RETIRED:
            raise ConflictError("The playbook is already retired", code="playbook_retired")
        version.status = PlaybookStatus.RETIRED.value
        version.retired_at = datetime.now(UTC)
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action="playbook.version_retired",
            actor_user_id=actor_user_id,
            target_type="playbook_version",
            target_id=version.id,
            details={"agent_id": str(version.agent_id), "version": version.version},
        )
        await self._session.commit()
        return version

    def _audit(self, action: str, entry: PlaybookEntry, actor_user_id: uuid.UUID | None) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action=action,
            actor_user_id=actor_user_id,
            target_type="playbook_entry",
            target_id=entry.id,
            details={"version_id": str(entry.version_id), "status": entry.status},
        )
