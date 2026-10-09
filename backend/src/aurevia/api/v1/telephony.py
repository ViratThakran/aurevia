"""Phone calls: outbound calls through the compliance gate, numbers, test numbers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Request, Response, status

from aurevia.compliance.gate import ComplianceGate
from aurevia.compliance.policy import POLICY_PACKS, TelephonyMode
from aurevia.errors import ServiceUnavailableError
from aurevia.identity.dependencies import AdminDep, PrincipalDep, SessionDep, SettingsDep
from aurevia.memory.service import LeadService
from aurevia.providers.dnd import DndRegistry
from aurevia.providers.telephony import TelephonyProvider
from aurevia.providers.voice_transport import VoiceTransport
from aurevia.telephony.models import PhoneNumber, TestNumber
from aurevia.telephony.numbers import NumberService
from aurevia.telephony.schemas import (
    OutboundCallIn,
    OutboundCallResponse,
    PhoneNumberIn,
    PhoneNumberResponse,
    PhoneNumberUpdate,
    TestNumberIn,
    TestNumberResponse,
)
from aurevia.telephony.service import AgentDispatch, create_outbound_call, dial
from aurevia.voice.service import AgentService, CallService

router = APIRouter(tags=["telephony"])


def _phone(number: PhoneNumber) -> PhoneNumberResponse:
    return PhoneNumberResponse.model_validate(number, from_attributes=True)


def _test_number(number: TestNumber) -> TestNumberResponse:
    return TestNumberResponse.model_validate(number, from_attributes=True)


@router.post(
    "/calls/outbound",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Call a lead by phone (only if the compliance gate allows it)",
)
async def place_outbound_call(
    body: OutboundCallIn,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> OutboundCallResponse:
    telephony: TelephonyProvider | None = request.app.state.telephony
    transport: VoiceTransport | None = request.app.state.voice_transport
    if telephony is None or transport is None:
        raise ServiceUnavailableError("Phone calls are not configured")
    assert settings.jwt_secret is not None  # noqa: S101 - authenticated requests imply it
    dnd: DndRegistry = request.app.state.dnd_registry

    lead = await LeadService(session, principal.tenant_id).get(body.lead_id)
    gate = ComplianceGate(
        session,
        principal.tenant_id,
        pack=POLICY_PACKS[settings.compliance_policy_pack],
        mode=TelephonyMode(settings.telephony_mode),
        dnd=dnd,
    )
    # Raises CallBlockedError (403) after recording the blocked decision.
    approval = await gate.check_outbound(
        lead=lead,
        purpose=body.purpose,
        requested_by=principal.user_id,
        now=request.app.state.clock(),
    )
    agent = await AgentService(session, principal.tenant_id).default_agent()
    call = await create_outbound_call(
        session,
        approval=approval,
        agent=agent,
        user_id=principal.user_id,
        now=request.app.state.clock(),
    )
    await session.commit()  # the allow decision and its call, together

    dispatch = AgentDispatch(
        agent_name=settings.livekit_agent_name,
        jwt_secret=settings.jwt_secret.get_secret_value(),
        call_token_ttl_seconds=settings.call_token_ttl_seconds,
    )
    try:
        await transport.open_room_with_agent(
            room=call.room, agent_name=dispatch.agent_name, metadata=dispatch.metadata(call)
        )
    except Exception as exc:
        await CallService(session, principal.tenant_id).end(
            call.id, "room_setup_failed", failed=True
        )
        raise ServiceUnavailableError("The voice service is unavailable") from exc
    background.add_task(
        dial,
        request.app.state.database,
        telephony,
        transport,
        approval=approval,
        call_id=call.id,
        room=call.room,
        ring_timeout_seconds=settings.ring_timeout_seconds,
    )
    return OutboundCallResponse(
        call_id=call.id, decision_id=approval.decision_id, dial_status="queued"
    )


@router.post(
    "/telephony/numbers",
    status_code=status.HTTP_201_CREATED,
    summary="Register a carrier number (owner/admin)",
)
async def add_phone_number(
    body: PhoneNumberIn, principal: AdminDep, session: SessionDep
) -> PhoneNumberResponse:
    number = await NumberService(session, principal.tenant_id).add_phone_number(
        body, principal.user_id
    )
    return _phone(number)


@router.get("/telephony/numbers", summary="The tenant's carrier numbers")
async def list_phone_numbers(
    principal: PrincipalDep, session: SessionDep
) -> list[PhoneNumberResponse]:
    return [
        _phone(n) for n in await NumberService(session, principal.tenant_id).list_phone_numbers()
    ]


@router.patch("/telephony/numbers/{number_id}", summary="Change a carrier number (owner/admin)")
async def update_phone_number(
    number_id: uuid.UUID, body: PhoneNumberUpdate, principal: AdminDep, session: SessionDep
) -> PhoneNumberResponse:
    number = await NumberService(session, principal.tenant_id).update_phone_number(
        number_id, body, principal.user_id
    )
    return _phone(number)


@router.post(
    "/telephony/test-numbers",
    status_code=status.HTTP_201_CREATED,
    summary="Register one of your own phones for test calls (owner/admin)",
)
async def add_test_number(
    body: TestNumberIn, principal: AdminDep, session: SessionDep, settings: SettingsDep
) -> TestNumberResponse:
    number = await NumberService(session, principal.tenant_id).add_test_number(
        body, principal.user_id, limit=settings.max_test_numbers
    )
    return _test_number(number)


@router.get("/telephony/test-numbers", summary="Your registered test numbers")
async def list_test_numbers(
    principal: PrincipalDep, session: SessionDep
) -> list[TestNumberResponse]:
    numbers = await NumberService(session, principal.tenant_id).list_test_numbers()
    return [_test_number(n) for n in numbers]


@router.delete(
    "/telephony/test-numbers/{number_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a test number (owner/admin)",
)
async def remove_test_number(
    number_id: uuid.UUID, principal: AdminDep, session: SessionDep
) -> Response:
    await NumberService(session, principal.tenant_id).remove_test_number(
        number_id, principal.user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
