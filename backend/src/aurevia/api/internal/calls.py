"""Call endpoints for the voice worker, authenticated by a per-call token.

The reply to a turn streams as NDJSON lines: ``{"type": "delta", "text": ...}`` while the
model writes, then exactly one ``{"type": "done", "sales_state": ...}`` or
``{"type": "error", "code": ...}``. When the worker cancels a reply (the prospect interrupted)
it simply closes the stream; generation stops and the usage is still recorded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError

from aurevia.conversation.engine import (
    ConversationEngine,
    InvalidHistoryError,
    TurnRecords,
    Utterance,
    to_model_messages,
)
from aurevia.conversation.prompt import PromptContext, RememberedFact
from aurevia.db.session import Database, set_tenant_context
from aurevia.errors import AureviaError, ConflictError, ServiceUnavailableError
from aurevia.gateway import GatewayError, ModelGateway
from aurevia.identity.dependencies import SessionDep, SettingsDep
from aurevia.memory.jobs import safe_remember_call
from aurevia.memory.models import Lead, Speaker
from aurevia.memory.schemas import TranscriptIn
from aurevia.memory.service import Line, MemoryService, TranscriptService
from aurevia.sales.scheduling import hours_for, spoken
from aurevia.sales.state import SalesState, after_prospect_turn
from aurevia.tools.framework import ToolContext, ToolExecutor, ToolRegistry
from aurevia.tools.sales_tools import default_registry
from aurevia.usage.models import UsageEvent
from aurevia.usage.recorder import record_llm_usage
from aurevia.voice.call_auth import CallPrincipalDep
from aurevia.voice.metrics import TurnMetric
from aurevia.voice.models import Call
from aurevia.voice.schemas import (
    CallEndRequest,
    CallStartResponse,
    TurnMetricsReport,
    TurnRequest,
    UsageReport,
)
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


# Bookkeeping passes still running, one per call. A new turn waits briefly for its call's pass,
# so the next prompt sees the stage it recorded and the two never write the call concurrently.
PENDING_BOOKKEEPING: dict[uuid.UUID, asyncio.Task[None]] = {}
BOOKKEEPING_WAIT_SECONDS = 2.0
# One retry for transient model failures (quota, timeout, outage), after this pause.
BOOKKEEPING_RETRY_SECONDS = 2.0
_RETRYABLE = frozenset({"rate_limited", "timeout", "unavailable"})


async def _wait_for_bookkeeping(call_id: uuid.UUID) -> None:
    task = PENDING_BOOKKEEPING.get(call_id)
    if task is None or task.done():
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=BOOKKEEPING_WAIT_SECONDS)
    except TimeoutError:
        logger.info(
            "Turn started before the previous bookkeeping pass finished",
            extra={"fields": {"call_id": str(call_id)}},
        )


def _track_bookkeeping(call_id: uuid.UUID, task: asyncio.Task[None]) -> None:
    PENDING_BOOKKEEPING[call_id] = task

    def forget(done: asyncio.Task[None]) -> None:
        if PENDING_BOOKKEEPING.get(call_id) is done:
            del PENDING_BOOKKEEPING[call_id]

    task.add_done_callback(forget)


async def _bookkeeping_pass(
    *,
    gateway: ModelGateway,
    database: Database,
    registry: ToolRegistry,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    records: TurnRecords,
    metadata: dict[str, str],
    now: datetime,
) -> None:
    async with database.sessionmaker() as session:
        await set_tenant_context(session, tenant_id)
        call = await session.get(Call, call_id)
        if call is None:
            return
        lead = await session.get(Lead, lead_id) if lead_id else None
        executor = ToolExecutor(
            registry,
            ToolContext(session=session, tenant_id=tenant_id, call=call, lead=lead, now=now),
        )
        await ConversationEngine(gateway).record_turn(
            records=records,
            new_record=lambda: gateway.new_record(metadata),
            tools=registry.specs(),
            executor=executor,
        )


async def _bookkeep(
    *,
    gateway: ModelGateway,
    database: Database,
    tenant_id: uuid.UUID,
    call_id: uuid.UUID,
    lead_id: uuid.UUID | None,
    records: TurnRecords,
    metadata: dict[str, str],
    now: datetime,
) -> None:
    """Second model call of a turn: record stage, qualification and objections.

    Failure here never affects the call: the reply was already spoken. A transient model
    failure is retried once; a pass that is still lost is logged as an error.
    """
    registry = default_registry()
    already = len(records.records)
    for attempt in (1, 2):
        try:
            await _bookkeeping_pass(
                gateway=gateway,
                database=database,
                registry=registry,
                tenant_id=tenant_id,
                call_id=call_id,
                lead_id=lead_id,
                records=records,
                metadata=metadata,
                now=now,
            )
        except GatewayError as exc:
            if attempt == 1 and exc.code in _RETRYABLE:
                logger.warning(
                    "Bookkeeping pass failed, retrying",
                    extra={"fields": {"call_id": str(call_id), "code": exc.code}},
                )
                await asyncio.sleep(BOOKKEEPING_RETRY_SECONDS)
                continue
            logger.error(
                "Bookkeeping pass lost",
                extra={"fields": {"call_id": str(call_id), "code": exc.code}},
            )
        except Exception:
            logger.exception("Bookkeeping pass lost", extra={"fields": {"call_id": str(call_id)}})
        break
    for record in records.records[already:]:
        await record_llm_usage(database, tenant_id=tenant_id, call_id=call_id, record=record)


@router.post("/turns", summary="Stream the agent's reply to the prospect's latest words")
async def take_turn(
    call_id: uuid.UUID,
    body: TurnRequest,
    request: Request,
    principal: CallPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> StreamingResponse:
    turn_started = time.monotonic()
    gateway: ModelGateway | None = request.app.state.model_gateway
    database: Database = request.app.state.database
    if gateway is None:
        raise ServiceUnavailableError("The AI model is not configured")

    await _wait_for_bookkeeping(call_id)
    calls = CallService(session, principal.tenant_id)
    call, agent = await calls.get_with_agent(call_id, for_update=True)
    require_in_progress(call)
    try:
        messages = to_model_messages([Utterance(role=u.role, text=u.text) for u in body.history])
    except InvalidHistoryError as exc:
        raise AureviaError(str(exc), status_code=422, code="invalid_history") from exc

    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    memories: list[RememberedFact] = []
    if lead is not None:
        memories = [
            RememberedFact(kind=m.kind, fact=m.fact)
            for m in await MemoryService(session, principal.tenant_id).for_prompt(
                lead.id,
                min_confidence=settings.memory_min_confidence,
                limit=settings.memory_max_facts_in_prompt,
            )
        ]
    hours = await hours_for(session, principal.tenant_id)
    now = datetime.now(UTC)
    context = PromptContext(
        memories=memories,
        prospect_name=lead.name if lead else None,
        prospect_company=lead.company if lead else None,
        now_spoken=f"{spoken(now, hours)} ({hours.timezone})",
    )
    state = after_prospect_turn(SalesState(call.sales_state))
    call.sales_state = state
    call.turn_count += 1
    profile = profile_of(agent)
    await session.commit()
    prepared_ms = round((time.monotonic() - turn_started) * 1000)

    registry = default_registry()
    records = TurnRecords()
    metadata = {"call_id": str(call_id), "tenant_id": str(principal.tenant_id)}

    async def stream() -> AsyncIterator[bytes]:
        final_state = state.value
        spoke = False
        failed = False
        try:
            # Tools write through their own session, scoped to this tenant and committed per
            # tool together with its audit row.
            async with database.sessionmaker() as tool_session:
                await set_tenant_context(tool_session, principal.tenant_id)
                tool_call = await tool_session.get(Call, call_id)
                tool_lead = await tool_session.get(Lead, lead.id) if lead else None
                assert tool_call is not None  # noqa: S101 - loaded above in the same tenant
                executor = ToolExecutor(
                    registry,
                    ToolContext(
                        session=tool_session,
                        tenant_id=principal.tenant_id,
                        call=tool_call,
                        lead=tool_lead,
                        now=now,
                    ),
                )
                async for event in ConversationEngine(gateway).stream_reply(
                    agent=profile,
                    state=state,
                    messages=messages,
                    new_record=lambda: gateway.new_record(metadata),
                    records=records,
                    context=context,
                    tools=registry.specs(),
                    executor=executor,
                ):
                    if event.delta:
                        if not spoke:
                            spoke = True
                            logger.info(
                                "Turn first word",
                                extra={
                                    "fields": {
                                        "call_id": str(call_id),
                                        "prepare_ms": prepared_ms,
                                        "first_word_ms": round(
                                            (time.monotonic() - turn_started) * 1000
                                        ),
                                        "rounds": len(records.records),
                                    }
                                },
                            )
                        yield _line({"type": "delta", "text": event.delta})
                    for result in event.tool_results:
                        yield _line(
                            {"type": "tool", "name": result.name, "ok": not result.is_error}
                        )
                final_state = tool_call.sales_state
            yield _line({"type": "done", "sales_state": final_state})
        except GatewayError as exc:
            failed = True
            logger.warning(
                "Model request failed",
                extra={"fields": {"call_id": str(call_id), "code": exc.code}},
            )
            yield _line({"type": "error", "code": exc.code})
        finally:
            for record in records.records:
                await record_llm_usage(
                    database, tenant_id=principal.tenant_id, call_id=call_id, record=record
                )
            if not failed:
                # The reply is out (or the prospect cut it off): record the turn off the
                # prospect's clock. A reference is kept so the task is not garbage collected.
                task = asyncio.create_task(
                    _bookkeep(
                        gateway=gateway,
                        database=database,
                        tenant_id=principal.tenant_id,
                        call_id=call_id,
                        lead_id=lead.id if lead else None,
                        records=records,
                        metadata=metadata,
                        now=now,
                    )
                )
                _track_bookkeeping(call_id, task)

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


@router.post(
    "/turn-metrics",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Report per-turn latency (timings only)",
)
async def report_turn_metrics(
    call_id: uuid.UUID, body: TurnMetricsReport, principal: CallPrincipalDep, session: SessionDep
) -> Response:
    await CallService(session, principal.tenant_id).get(call_id)  # 404 if not this tenant's
    seqs = [turn.seq for turn in body.turns]
    if len(set(seqs)) != len(seqs):
        raise AureviaError("Duplicate turn seq", status_code=422, code="duplicate_seq")
    session.add_all(
        TurnMetric(tenant_id=principal.tenant_id, call_id=call_id, **turn.model_dump())
        for turn in body.turns
    )
    try:
        await session.commit()
    except IntegrityError as exc:  # the same turns reported twice
        await session.rollback()
        raise ConflictError("Turn metrics already reported", code="duplicate_seq") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/transcript",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save what was said (kept until the retention period ends)",
)
async def save_transcript(
    call_id: uuid.UUID,
    body: TranscriptIn,
    principal: CallPrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    await CallService(session, principal.tenant_id).get(call_id)  # 404 if not this tenant's
    seqs = [line.seq for line in body.lines]
    if len(set(seqs)) != len(seqs):
        raise AureviaError("Duplicate line seq", status_code=422, code="duplicate_seq")
    await TranscriptService(session, principal.tenant_id).save(
        call_id,
        [Line(seq=ln.seq, speaker=Speaker(ln.speaker), text=ln.text) for ln in body.lines],
        retention_days=settings.transcript_retention_days,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/end", status_code=status.HTTP_204_NO_CONTENT, summary="Worker left: end the call")
async def end_call(
    call_id: uuid.UUID,
    body: CallEndRequest,
    request: Request,
    background: BackgroundTasks,
    principal: CallPrincipalDep,
    session: SessionDep,
) -> Response:
    call = await CallService(session, principal.tenant_id).end(
        call_id, body.reason, failed=body.failed
    )
    gateway: ModelGateway | None = request.app.state.model_gateway
    if call.lead_id is not None and gateway is not None:
        # After the response: the caller has gone, and extraction never delays the worker.
        background.add_task(
            safe_remember_call,
            request.app.state.database,
            gateway,
            tenant_id=principal.tenant_id,
            call_id=call_id,
            lead_id=call.lead_id,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
