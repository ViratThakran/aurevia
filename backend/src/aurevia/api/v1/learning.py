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
from aurevia.learning.labels import LabelIn, LabelReviewIn
from aurevia.learning.models import (
    LearningLabel,
    LearningSource,
    LearningTechnique,
    ReviewStatus,
    TechniqueStatus,
)
from aurevia.learning.redaction import GatewayDetector, RedactionError
from aurevia.learning.schemas import (
    LabelAccuracyOut,
    LabelOut,
    LineOut,
    SourceDetailOut,
    SourceImportIn,
    SourceOut,
    TechniqueEditIn,
    TechniqueIn,
    TechniqueOut,
    TechniqueReviewIn,
    TechniqueToPlaybookIn,
)
from aurevia.learning.service import LearningService
from aurevia.learning.techniques import TechniqueService


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


def _label(label: LearningLabel) -> LabelOut:
    return LabelOut.model_validate(label, from_attributes=True)


@router.get("/sources/{source_id}/labels", summary="Labels on one source (WP-12.4)")
async def list_labels(
    source_id: uuid.UUID, principal: LearningReviewDep, session: SessionDep
) -> list[LabelOut]:
    labels = await LearningService(session, principal.tenant_id).labels(source_id)
    return [_label(label) for label in labels]


@router.post(
    "/sources/{source_id}/labels",
    status_code=status.HTTP_201_CREATED,
    summary="Add a person's label (stored as checked by them)",
)
async def add_label(
    source_id: uuid.UUID, body: LabelIn, principal: LearningReviewDep, session: SessionDep
) -> LabelOut:
    label = await LearningService(session, principal.tenant_id).add_label(
        source_id, body, actor_user_id=principal.user_id
    )
    return _label(label)


@router.post("/labels/{label_id}/review", summary="Approve or reject a proposed label")
async def review_label(
    label_id: uuid.UUID, body: LabelReviewIn, principal: LearningReviewDep, session: SessionDep
) -> LabelOut:
    label = await LearningService(session, principal.tenant_id).review_label(
        label_id, ReviewStatus(body.status), actor_user_id=principal.user_id
    )
    return _label(label)


@router.get("/labels/accuracy", summary="How the model's proposed labels fared when checked")
async def label_accuracy(principal: LearningReviewDep, session: SessionDep) -> LabelAccuracyOut:
    return await LearningService(session, principal.tenant_id).label_accuracy()


def _technique(technique: LearningTechnique) -> TechniqueOut:
    return TechniqueOut.model_validate(technique, from_attributes=True)


@router.get("/techniques", summary="The technique review queue (WP-12.6), newest first")
async def list_techniques(
    principal: LearningReviewDep,
    session: SessionDep,
    status: TechniqueStatus | None = TechniqueStatus.PROPOSED,
) -> list[TechniqueOut]:
    rows = await TechniqueService(session, principal.tenant_id).queue(status)
    return [_technique(t) for t in rows]


@router.post(
    "/techniques",
    status_code=201,
    summary="Add a technique candidate; the policy check runs first",
)
async def propose_technique(
    body: TechniqueIn, principal: LearningReviewDep, session: SessionDep
) -> TechniqueOut:
    technique = await TechniqueService(session, principal.tenant_id).propose(
        body, actor_user_id=principal.user_id
    )
    return _technique(technique)


@router.put(
    "/techniques/{technique_id}",
    summary="Edit a candidate; it is checked again and goes back to the queue",
)
async def edit_technique(
    technique_id: uuid.UUID,
    body: TechniqueEditIn,
    principal: LearningReviewDep,
    session: SessionDep,
) -> TechniqueOut:
    technique = await TechniqueService(session, principal.tenant_id).edit(
        technique_id, body, actor_user_id=principal.user_id
    )
    return _technique(technique)


@router.post(
    "/techniques/{technique_id}/review",
    summary="Approve or reject a candidate (a flagged one cannot be approved)",
)
async def review_technique(
    technique_id: uuid.UUID,
    body: TechniqueReviewIn,
    principal: LearningReviewDep,
    session: SessionDep,
) -> TechniqueOut:
    technique = await TechniqueService(session, principal.tenant_id).review(
        technique_id, TechniqueStatus(body.status), actor_user_id=principal.user_id
    )
    return _technique(technique)


@router.post(
    "/techniques/{technique_id}/to-playbook",
    summary="Copy an approved technique into a draft playbook as a proposed entry",
)
async def technique_to_playbook(
    technique_id: uuid.UUID,
    body: TechniqueToPlaybookIn,
    principal: LearningReviewDep,
    session: SessionDep,
) -> TechniqueOut:
    technique = await TechniqueService(session, principal.tenant_id).copy_to_playbook(
        technique_id, body.version_id, actor_user_id=principal.user_id
    )
    return _technique(technique)
