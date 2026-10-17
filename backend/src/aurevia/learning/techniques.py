"""Technique review queue (WP-12.6, built early; off unless ``AUREVIA_LEARNING_ENABLED``).

Every candidate passes the automatic policy check first (``learning.policy``); a flagged one
cannot be approved until it is edited and passes. A person approves, edits or rejects; every
decision is audited. An approved technique can be copied into a draft playbook, where it is a
``proposed`` entry until someone with ``learning.publish`` approves it there.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import AureviaError, ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.learning.models import (
    LabelSource,
    LearningSource,
    LearningTechnique,
    SourceOutcome,
    TechniqueStatus,
)
from aurevia.learning.policy import FLAG_TEXT, policy_flags
from aurevia.learning.schemas import TechniqueEditIn, TechniqueIn
from aurevia.playbooks.schemas import EntryIn
from aurevia.playbooks.service import PlaybookService
from aurevia.sales.state import SalesState


class TechniqueService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def queue(
        self, status: TechniqueStatus | None, limit: int = 200
    ) -> list[LearningTechnique]:
        query = select(LearningTechnique).where(LearningTechnique.tenant_id == self._tenant_id)
        if status is not None:
            query = query.where(LearningTechnique.status == status.value)
        rows = await self._session.scalars(
            query.order_by(LearningTechnique.created_at.desc()).limit(limit)
        )
        return list(rows)

    async def _get(self, technique_id: uuid.UUID) -> LearningTechnique:
        technique = await self._session.scalar(
            select(LearningTechnique)
            .where(
                LearningTechnique.id == technique_id,
                LearningTechnique.tenant_id == self._tenant_id,
            )
            .with_for_update()
        )
        if technique is None:
            raise NotFoundError("Technique not found")
        return technique

    async def propose(
        self, body: TechniqueIn, *, actor_user_id: uuid.UUID | None
    ) -> LearningTechnique:
        source_ids = list(dict.fromkeys(body.source_ids))
        outcomes = list(
            await self._session.scalars(
                select(LearningSource.outcome).where(
                    LearningSource.tenant_id == self._tenant_id,
                    LearningSource.id.in_(source_ids),
                )
            )
        )
        if len(outcomes) != len(source_ids):
            raise NotFoundError("Learning source not found")
        technique = LearningTechnique(
            tenant_id=self._tenant_id,
            stage=body.stage.value if body.stage else None,
            situation=body.situation,
            says=body.says,
            tone=body.tone,
            goal=body.goal,
            conditions=body.conditions,
            excerpt=body.excerpt,
            source_ids=source_ids,
            booked_count=outcomes.count(SourceOutcome.BOOKED.value),
            unbooked_count=outcomes.count(SourceOutcome.NOT_BOOKED.value),
            proposed_by=LabelSource.PERSON.value,
            policy_flags=policy_flags(body.situation, body.says, body.goal, body.excerpt),
            status=TechniqueStatus.PROPOSED.value,
        )
        self._session.add(technique)
        await self._session.flush()
        self._audit("learning.technique_proposed", technique, actor_user_id)
        await self._session.commit()
        return technique

    async def edit(
        self, technique_id: uuid.UUID, body: TechniqueEditIn, *, actor_user_id: uuid.UUID | None
    ) -> LearningTechnique:
        """Change a candidate. It is checked again and goes back to the queue as proposed."""
        technique = await self._get(technique_id)
        if technique.playbook_entry_id is not None:
            raise ConflictError(
                "Already copied into a playbook; change it there", code="technique_in_playbook"
            )
        technique.stage = body.stage.value if body.stage else None
        technique.situation, technique.says = body.situation, body.says
        technique.tone, technique.goal, technique.conditions = body.tone, body.goal, body.conditions
        technique.policy_flags = policy_flags(
            body.situation, body.says, body.goal, technique.excerpt
        )
        technique.status = TechniqueStatus.PROPOSED.value
        technique.reviewed_by_user_id = None
        technique.reviewed_at = None
        self._audit("learning.technique_edited", technique, actor_user_id)
        await self._session.commit()
        return technique

    async def review(
        self,
        technique_id: uuid.UUID,
        status: TechniqueStatus,
        *,
        actor_user_id: uuid.UUID | None,
    ) -> LearningTechnique:
        technique = await self._get(technique_id)
        if technique.playbook_entry_id is not None:
            raise ConflictError(
                "Already copied into a playbook; change it there", code="technique_in_playbook"
            )
        if status == TechniqueStatus.APPROVED and technique.policy_flags:
            raise AureviaError(
                "This technique fails the policy check; edit it first",
                status_code=409,
                code="technique_flagged",
                details={"reasons": [FLAG_TEXT[f] for f in technique.policy_flags]},
            )
        technique.status = status.value
        technique.reviewed_by_user_id = actor_user_id
        technique.reviewed_at = datetime.now(UTC)
        self._audit("learning.technique_reviewed", technique, actor_user_id)
        await self._session.commit()
        return technique

    async def copy_to_playbook(
        self, technique_id: uuid.UUID, version_id: uuid.UUID, *, actor_user_id: uuid.UUID | None
    ) -> LearningTechnique:
        """Add an approved technique to a draft playbook as a proposed entry (one transaction)."""
        technique = await self._get(technique_id)
        if technique.status != TechniqueStatus.APPROVED or technique.policy_flags:
            raise ConflictError("Only an approved technique can go into a playbook")
        if technique.playbook_entry_id is not None:
            raise ConflictError("Already in a playbook", code="technique_in_playbook")
        seen = len(technique.source_ids)
        entry = await PlaybookService(self._session, self._tenant_id).add_entry(
            version_id,
            EntryIn(
                stage=SalesState(technique.stage) if technique.stage else None,
                situation=technique.situation,
                says=technique.says,
                tone=technique.tone,
                goal=technique.goal,
                source=(
                    f"Expert technique seen in {seen} source{'s' if seen != 1 else ''} "
                    f"({technique.booked_count} booked, {technique.unbooked_count} not booked)"
                ),
            ),
            actor_user_id=actor_user_id,
            commit=False,
        )
        technique.playbook_entry_id = entry.id
        self._audit("learning.technique_to_playbook", technique, actor_user_id)
        await self._session.commit()
        return technique

    def _audit(
        self, action: str, technique: LearningTechnique, actor_user_id: uuid.UUID | None
    ) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            action=action,
            actor_user_id=actor_user_id,
            target_type="learning_technique",
            target_id=technique.id,
            details={
                "status": technique.status,
                "policy_flags": list(technique.policy_flags),
                "playbook_entry_id": str(technique.playbook_entry_id)
                if technique.playbook_entry_id
                else None,
            },
        )
