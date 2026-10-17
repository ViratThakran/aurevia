"""Learning API (WP-12.3, built early; off unless ``AUREVIA_LEARNING_ENABLED``)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from aurevia.errors import AureviaError, NotFoundError, ServiceUnavailableError
from aurevia.gateway import ModelGateway
from aurevia.identity.dependencies import (
    LearningImportDep,
    LearningReviewDep,
    SessionDep,
    SettingsDep,
)
from aurevia.learning.models import LearningSource
from aurevia.learning.redaction import GatewayDetector, RedactionError
from aurevia.learning.schemas import LineOut, SourceDetailOut, SourceImportIn, SourceOut
from aurevia.learning.service import LearningService


async def _enabled(settings: SettingsDep) -> None:
    if not settings.learning_enabled:
        raise NotFoundError("Not found")


router = APIRouter(prefix="/learning", tags=["learning"], dependencies=[Depends(_enabled)])


def _out(source: LearningSource) -> SourceOut:
    return SourceOut.model_validate(source, from_attributes=True)


@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    summary="Import a transcript; it is redacted before anything is stored",
)
async def import_source(
    body: SourceImportIn, request: Request, principal: LearningImportDep, session: SessionDep
) -> SourceOut:
    gateway: ModelGateway | None = request.app.state.model_gateway
    if gateway is None:
        # Names and addresses need the model detector; never store text without it.
        raise ServiceUnavailableError("Redaction needs the AI model, which is not configured")
    try:
        source = await LearningService(session, principal.tenant_id).import_source(
            body, detector=GatewayDetector(gateway), actor_user_id=principal.user_id
        )
    except RedactionError as exc:
        await session.rollback()
        raise AureviaError(
            "Redaction failed, so nothing was stored", status_code=503, code="redaction_failed"
        ) from exc
    return _out(source)


@router.get("/sources", summary="Imported learning sources, newest first")
async def list_sources(
    principal: LearningReviewDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SourceOut]:
    sources = await LearningService(session, principal.tenant_id).list_sources(limit)
    return [_out(s) for s in sources]


@router.get("/sources/{source_id}", summary="One source with its redacted transcript")
async def get_source(
    source_id: uuid.UUID, principal: LearningReviewDep, session: SessionDep
) -> SourceDetailOut:
    source, lines = await LearningService(session, principal.tenant_id).get_source(source_id)
    return SourceDetailOut(
        **_out(source).model_dump(),
        lines=[LineOut.model_validate(line, from_attributes=True) for line in lines],
    )
