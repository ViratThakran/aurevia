"""Playbook API (WP-12.7 and 12.A, built early; off unless ``AUREVIA_PLAYBOOKS_ENABLED``).

Reading and drafting need ``learning.review``. Approving an entry and activating or retiring
a version need ``learning.publish``: nothing is used in a call until a person approves it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from aurevia.errors import NotFoundError
from aurevia.identity.dependencies import (
    LearningPublishDep,
    LearningReviewDep,
    SessionDep,
    SettingsDep,
)
from aurevia.playbooks.models import PlaybookEntry, PlaybookVersion
from aurevia.playbooks.schemas import (
    EntryIn,
    EntryOut,
    VersionCreateIn,
    VersionDetailOut,
    VersionOut,
)
from aurevia.playbooks.service import PlaybookService


async def _enabled(settings: SettingsDep) -> None:
    if not settings.playbooks_enabled:
        raise NotFoundError("Not found")


router = APIRouter(prefix="/playbooks", tags=["playbooks"], dependencies=[Depends(_enabled)])


def _version(version: PlaybookVersion) -> VersionOut:
    return VersionOut.model_validate(version, from_attributes=True)


def _entry(entry: PlaybookEntry) -> EntryOut:
    return EntryOut.model_validate(entry, from_attributes=True)


@router.get("", summary="Playbook versions, per agent, newest first")
async def list_versions(
    principal: LearningReviewDep, session: SessionDep, agent_id: uuid.UUID | None = None
) -> list[VersionOut]:
    versions = await PlaybookService(session, principal.tenant_id).list_versions(agent_id)
    return [_version(v) for v in versions]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Start a draft: empty, from the seed entries, or copied from a version",
)
async def create_version(
    body: VersionCreateIn, principal: LearningReviewDep, session: SessionDep
) -> VersionOut:
    version = await PlaybookService(session, principal.tenant_id).create_version(
        body, actor_user_id=principal.user_id
    )
    return _version(version)


@router.get("/{version_id}", summary="One playbook version with its entries")
async def get_version(
    version_id: uuid.UUID, principal: LearningReviewDep, session: SessionDep
) -> VersionDetailOut:
    service = PlaybookService(session, principal.tenant_id)
    version = await service.get_version(version_id)
    entries = await service.entries(version.id)
    return VersionDetailOut(**_version(version).model_dump(), entries=[_entry(e) for e in entries])


@router.post(
    "/{version_id}/entries",
    status_code=status.HTTP_201_CREATED,
    summary="Add an entry to a draft (as proposed)",
)
async def add_entry(
    version_id: uuid.UUID, body: EntryIn, principal: LearningReviewDep, session: SessionDep
) -> EntryOut:
    entry = await PlaybookService(session, principal.tenant_id).add_entry(
        version_id, body, actor_user_id=principal.user_id
    )
    return _entry(entry)


@router.put(
    "/{version_id}/entries/{entry_id}",
    summary="Change an entry in a draft; it goes back to proposed",
)
async def edit_entry(
    version_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: EntryIn,
    principal: LearningReviewDep,
    session: SessionDep,
) -> EntryOut:
    entry = await PlaybookService(session, principal.tenant_id).edit_entry(
        version_id, entry_id, body, actor_user_id=principal.user_id
    )
    return _entry(entry)


@router.post("/{version_id}/entries/{entry_id}/approve", summary="Approve an entry in a draft")
async def approve_entry(
    version_id: uuid.UUID, entry_id: uuid.UUID, principal: LearningPublishDep, session: SessionDep
) -> EntryOut:
    entry = await PlaybookService(session, principal.tenant_id).approve_entry(
        version_id, entry_id, actor_user_id=principal.user_id
    )
    return _entry(entry)


@router.post(
    "/{version_id}/activate",
    summary="Freeze a draft as the agent's active playbook (the previous one retires)",
)
async def activate(
    version_id: uuid.UUID, principal: LearningPublishDep, session: SessionDep
) -> VersionOut:
    version = await PlaybookService(session, principal.tenant_id).activate(
        version_id, actor_user_id=principal.user_id
    )
    return _version(version)


@router.post("/{version_id}/retire", summary="Retire a draft or the active version")
async def retire(
    version_id: uuid.UUID, principal: LearningPublishDep, session: SessionDep
) -> VersionOut:
    version = await PlaybookService(session, principal.tenant_id).retire(
        version_id, actor_user_id=principal.user_id
    )
    return _version(version)
