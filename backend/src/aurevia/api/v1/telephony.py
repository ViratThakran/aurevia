"""Phone calls: outbound calls through the compliance gate, numbers, test numbers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Request, Response, status

from aurevia.campaigns.service import CampaignService
from aurevia.identity.dependencies import (
    CallsDep,
    NumbersDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
)
from aurevia.memory.service import LeadService
from aurevia.telephony.models import PhoneNumber, TestNumber
from aurevia.telephony.numbers import NumberService
from aurevia.telephony.outbound import outbound_deps, place_outbound
from aurevia.telephony.schemas import (
    OutboundCallIn,
    OutboundCallResponse,
    PhoneNumberIn,
    PhoneNumberResponse,
    PhoneNumberUpdate,
    TestNumberIn,
    TestNumberResponse,
)

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
    principal: CallsDep,
    session: SessionDep,
    settings: SettingsDep,
    background: BackgroundTasks,
) -> OutboundCallResponse:
    deps = outbound_deps(request.app.state)
    lead = await LeadService(session, principal.tenant_id).get(body.lead_id)
    campaign = None
    if body.campaign_id is not None:
        campaign = await CampaignService(session, principal.tenant_id).get(body.campaign_id)
    placed = await place_outbound(
        session,
        deps,
        tenant_id=principal.tenant_id,
        lead=lead,
        purpose=body.purpose,
        campaign=campaign,
        requested_by=principal.user_id,
        schedule=lambda job: background.add_task(job),
    )
    return OutboundCallResponse(
        call_id=placed.call_id, decision_id=placed.decision_id, dial_status="queued"
    )


@router.post(
    "/telephony/numbers",
    status_code=status.HTTP_201_CREATED,
    summary="Register a carrier number (owner/admin)",
)
async def add_phone_number(
    body: PhoneNumberIn, principal: NumbersDep, session: SessionDep
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
    number_id: uuid.UUID, body: PhoneNumberUpdate, principal: NumbersDep, session: SessionDep
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
    body: TestNumberIn, principal: NumbersDep, session: SessionDep, settings: SettingsDep
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
    number_id: uuid.UUID, principal: NumbersDep, session: SessionDep
) -> Response:
    await NumberService(session, principal.tenant_id).remove_test_number(
        number_id, principal.user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
