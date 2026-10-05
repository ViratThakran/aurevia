"""Call endpoints for the voice worker, authenticated by a per-call token.

The reply to a turn streams as NDJSON lines: ``{"type": "delta", "text": ...}`` while the
model writes, then exactly one ``{"type": "done", "sales_state": ...}`` or
``{"type": "error", "code": ...}``. When the worker cancels a reply (the prospect interrupted)
it simply closes the stream; generation stops and the usage is still recorded.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import StreamingResponse

from aurevia.conversation.engine import (
    ConversationEngine,
    InvalidHistoryError,
    Utterance,
)
from aurevia.db.session import Database
from aurevia.errors import AureviaError, ServiceUnavailableError
from aurevia.gateway import GatewayError, ModelGateway
from aurevia.identity.dependencies import SessionDep
from aurevia.sales.state import SalesState, after_prospect_turn
from aurevia.usage.models import UsageEvent
from aurevia.usage.recorder import record_llm_usage
from aurevia.voice.call_auth import CallPrincipalDep
from aurevia.voice.schemas import CallEndRequest, CallStartResponse, TurnRequest, UsageReport
from aurevia.voice.service import CallService, profile_of, require_in_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls/{call_id}", tags=["internal: voice worker"])


def _line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload) + "\n").encode()


@router.post("/start", summary="Worker joined: start the call, get the agent's opening")
async def start_call(
    call_id: uuid.UUID, principal: CallPrincipalDep, session: SessionDep
) -> CallStartResponse:
    _, agent = await CallService(session, principal.tenant_id).start(call_id)
    return CallStartResponse(
        agent_name=agent.name, greeting=agent.greeting, language=agent.language, voice=agent.voice
    )


@router.post("/turns", summary="Stream the agent's reply to the prospect's latest words")
async def take_turn(
    call_id: uuid.UUID,
    body: TurnRequest,
    request: Request,
    principal: CallPrincipalDep,
    session: SessionDep,
) -> StreamingResponse:
    gateway: ModelGateway | None = request.app.state.model_gateway
    database: Database = request.app.state.database
    if gateway is None:
        raise ServiceUnavailableError("The AI model is not configured")

    calls = CallService(session, principal.tenant_id)
    call, agent = await calls.get_with_agent(call_id, for_update=True)
    require_in_progress(call)
    history = [Utterance(role=u.role, text=u.text) for u in body.history]
    engine = ConversationEngine(gateway)
    record = gateway.new_record({"call_id": str(call_id), "tenant_id": str(principal.tenant_id)})
    state = after_prospect_turn(SalesState(call.sales_state))
    try:
        replies = engine.stream_reply(
            agent=profile_of(agent), state=state, history=history, record=record
        )
    except InvalidHistoryError as exc:
        raise AureviaError(str(exc), status_code=422, code="invalid_history") from exc
    call.sales_state = state
    call.turn_count += 1
    await session.commit()

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for delta in replies:
                yield _line({"type": "delta", "text": delta})
            yield _line({"type": "done", "sales_state": state.value})
        except GatewayError as exc:
            logger.warning(
                "Model request failed",
                extra={"fields": {"call_id": str(call_id), "code": exc.code}},
            )
            yield _line({"type": "error", "code": exc.code})
        finally:
            await record_llm_usage(
                database, tenant_id=principal.tenant_id, call_id=call_id, record=record
            )

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/usage", status_code=status.HTTP_204_NO_CONTENT, summary="Report STT/TTS usage")
async def report_usage(
    call_id: uuid.UUID, body: UsageReport, principal: CallPrincipalDep, session: SessionDep
) -> Response:
    await CallService(session, principal.tenant_id).get(call_id)  # 404 if not this tenant's
    session.add(
        UsageEvent(
            tenant_id=principal.tenant_id,
            call_id=call_id,
            kind=body.kind,
            provider=body.provider,
            model=body.model,
            audio_seconds=body.audio_seconds,
            characters=body.characters,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/end", status_code=status.HTTP_204_NO_CONTENT, summary="Worker left: end the call")
async def end_call(
    call_id: uuid.UUID, body: CallEndRequest, principal: CallPrincipalDep, session: SessionDep
) -> Response:
    await CallService(session, principal.tenant_id).end(call_id, body.reason, failed=body.failed)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
