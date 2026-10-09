"""Agents and the call lifecycle. Every query runs in the tenant's RLS scope and filters on
``tenant_id`` explicitly, like the identity services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.conversation.prompt import AgentProfile
from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.identity.models import Tenant
from aurevia.sales.state import SalesState, transition
from aurevia.voice.models import Agent, Call, CallChannel, CallStatus

DEFAULT_AGENT_NAME = "Aria"


@dataclass(frozen=True)
class AgentSettings:
    """Validated agent configuration (see ``voice.schemas.AgentUpdate``)."""

    name: str
    company_name: str
    company_description: str
    objective: str
    greeting: str
    language: str
    voice: str | None


def profile_of(agent: Agent) -> AgentProfile:
    return AgentProfile(
        name=agent.name,
        company_name=agent.company_name,
        company_description=agent.company_description,
        objective=agent.objective,
        language=agent.language,
    )


def room_name(call_id: uuid.UUID) -> str:
    return f"aurevia-call-{call_id.hex}"


class AgentService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def default_agent(self) -> Agent:
        agent = await self._session.scalar(
            select(Agent).where(Agent.tenant_id == self._tenant_id, Agent.is_default.is_(True))
        )
        if agent is not None:
            return agent
        tenant = await self._session.scalar(select(Tenant).where(Tenant.id == self._tenant_id))
        if tenant is None:
            raise NotFoundError("Tenant not found")
        agent = Agent(
            tenant_id=self._tenant_id,
            is_default=True,
            name=DEFAULT_AGENT_NAME,
            company_name=tenant.name,
            company_description=(
                "No company details have been configured yet. Do not describe the company's "
                "products or prices; offer that a colleague will share details."
            ),
            objective=(
                "Introduce the company, understand what the prospect needs, and agree that a "
                "colleague will follow up."
            ),
            greeting=(
                f"Hi, this is {DEFAULT_AGENT_NAME}, an AI assistant calling from {tenant.name}. "
                "Is now a good time for a quick chat?"
            ),
            language="en-IN",
            voice=None,
        )
        self._session.add(agent)
        await self._session.flush()
        return agent

    async def update_default_agent(self, values: AgentSettings, actor: uuid.UUID) -> Agent:
        agent = await self.default_agent()
        agent.name = values.name
        agent.company_name = values.company_name
        agent.company_description = values.company_description
        agent.objective = values.objective
        agent.greeting = values.greeting
        agent.language = values.language
        agent.voice = values.voice
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action="agent.updated",
            target_type="agent",
            target_id=agent.id,
        )
        await self._session.commit()
        return agent


class CallService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create_browser_call(
        self, *, agent: Agent, user_id: uuid.UUID, lead_id: uuid.UUID | None = None
    ) -> Call:
        call_id = uuid.uuid4()
        call = Call(
            id=call_id,
            tenant_id=self._tenant_id,
            agent_id=agent.id,
            lead_id=lead_id,
            created_by_user_id=user_id,
            channel=CallChannel.BROWSER,
            status=CallStatus.CREATED,
            sales_state=SalesState.NEW,
            room=room_name(call_id),
        )
        self._session.add(call)
        await self._session.flush()
        return call

    async def get(self, call_id: uuid.UUID) -> Call:
        call = await self._session.scalar(
            select(Call).where(Call.id == call_id, Call.tenant_id == self._tenant_id)
        )
        if call is None:
            raise NotFoundError("Call not found")
        return call

    async def get_with_agent(self, call_id: uuid.UUID, *, for_update: bool) -> tuple[Call, Agent]:
        query = (
            select(Call, Agent)
            .join(Agent, Agent.id == Call.agent_id)
            .where(Call.id == call_id, Call.tenant_id == self._tenant_id)
        )
        if for_update:
            query = query.with_for_update(of=Call)
        row = (await self._session.execute(query)).first()
        if row is None:
            raise NotFoundError("Call not found")
        return row.Call, row.Agent

    async def start(self, call_id: uuid.UUID) -> tuple[Call, Agent]:
        call, agent = await self.get_with_agent(call_id, for_update=True)
        if call.status != CallStatus.CREATED:
            raise ConflictError("Call already started", code="call_already_started")
        call.status = CallStatus.IN_PROGRESS
        call.started_at = datetime.now(UTC)
        call.sales_state = transition(SalesState(call.sales_state), SalesState.OPENING)
        await self._session.commit()
        return call, agent

    async def end(self, call_id: uuid.UUID, reason: str, *, failed: bool = False) -> Call:
        call = await self.get(call_id)
        if call.status in (CallStatus.COMPLETED, CallStatus.FAILED):
            return call  # ending twice is harmless
        call.status = CallStatus.FAILED if failed else CallStatus.COMPLETED
        call.ended_at = datetime.now(UTC)
        call.end_reason = reason
        call.sales_state = SalesState.COMPLETED
        await self._session.commit()
        return call


def require_in_progress(call: Call) -> None:
    if call.status != CallStatus.IN_PROGRESS:
        raise ConflictError("Call is not in progress", code="call_not_in_progress")
