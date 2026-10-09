"""The pre-call compliance gate: gather facts, apply the policy pack, record the decision.

``check_outbound`` is the only place an ``Approval`` is created, and the dialer accepts nothing
else (``tests/test_architecture.py`` enforces both). Every request leaves a decision record,
allowed or blocked. A blocked decision is committed before the error is raised; an allowed one
is committed by the caller in the same transaction as the call it allows.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.campaigns.models import Campaign
from aurevia.compliance.checks import (
    CallerIdFact,
    CampaignFact,
    ConsentFact,
    GateFacts,
    GateOutcome,
    evaluate,
    missing_disclosures,
)
from aurevia.compliance.models import ComplianceDecision, Consent, DoNotCallEntry, GateDecision
from aurevia.compliance.phone import normalize_e164
from aurevia.compliance.policy import CallPurpose, ConsentKind, PolicyPack, TelephonyMode
from aurevia.errors import AureviaError
from aurevia.memory.models import Lead
from aurevia.providers.dnd import DndRegistry, DndStatus
from aurevia.telephony.models import PhoneNumber, TestNumber
from aurevia.voice.models import Agent, Call, CallDirection

OUTBOUND_CALL = "outbound_call"
_GATE_KEY = object()


class CallBlockedError(AureviaError):
    status_code = 403
    code = "call_blocked"


@dataclass(frozen=True)
class Approval:
    """Proof that the gate allowed one specific call. Only ``ComplianceGate`` creates these."""

    decision_id: uuid.UUID
    tenant_id: uuid.UUID
    lead_id: uuid.UUID
    to_number: str
    from_number: str
    purpose: CallPurpose
    issued_at: datetime
    campaign_id: uuid.UUID | None = None
    _key: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._key is not _GATE_KEY:
            raise PermissionError("Approvals are issued only by the compliance gate")


class ComplianceGate:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        pack: PolicyPack,
        mode: TelephonyMode,
        dnd: DndRegistry,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._pack = pack
        self._mode = mode
        self._dnd = dnd

    async def check_outbound(
        self,
        *,
        lead: Lead,
        purpose: CallPurpose,
        requested_by: uuid.UUID | None,
        agent: Agent,
        campaign: Campaign | None = None,
        now: datetime | None = None,
    ) -> Approval:
        now = now or datetime.now(UTC)
        if campaign is not None:
            # Serialize decisions within a campaign, so its daily cap cannot be overrun.
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"campaign:{campaign.id}"},
            )
        to_number = normalize_e164(lead.phone, default_country_code=self._pack.country_code)
        if to_number is not None:
            # Serialize decisions for one number, so concurrent requests cannot both pass the
            # attempt limit.
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"{self._tenant_id}:{to_number}"},
            )
        facts, recorded = await self._facts(lead, to_number, purpose, now)
        missing = missing_disclosures(
            self._pack.required_disclosures,
            greeting=agent.greeting,
            agent_name=agent.name,
            company_name=agent.company_name,
        )
        campaign_fact = await self._campaign_fact(campaign, lead, now)
        facts = dataclasses.replace(facts, missing_disclosures=missing, campaign=campaign_fact)
        recorded["missing_disclosures"] = list(missing)
        recorded["campaign"] = (
            None
            if campaign_fact is None
            else {
                "status": campaign_fact.status,
                "attempts_for_lead": campaign_fact.attempts_for_lead,
                "calls_today": campaign_fact.calls_today,
            }
        )
        recorded["effective_policy"] = effective_policy_json(self._pack)
        outcome = evaluate(self._pack, facts, now)
        decision = self._record(lead, purpose, facts, recorded, outcome, requested_by)
        decision.campaign_id = campaign.id if campaign else None
        self._session.add(decision)
        await self._session.flush()
        if not outcome.allowed:
            await self._session.commit()
            raise CallBlockedError(
                "The compliance gate blocked this call",
                details={"decision_id": str(decision.id), "reasons": outcome.failed_reasons},
            )
        assert to_number is not None and outcome.from_number is not None  # noqa: S101 - allowed
        return Approval(
            decision_id=decision.id,
            tenant_id=self._tenant_id,
            lead_id=lead.id,
            to_number=to_number,
            from_number=outcome.from_number,
            purpose=purpose,
            issued_at=now,
            campaign_id=campaign.id if campaign else None,
            _key=_GATE_KEY,
        )

    async def _facts(
        self, lead: Lead, to_number: str | None, purpose: CallPurpose, now: datetime
    ) -> tuple[GateFacts, dict[str, object]]:
        tenant = self._tenant_id
        is_test = on_dnc = False
        consents: tuple[ConsentFact, ...] = ()
        calls_today = calls_week = 0
        dnd, dnd_source = DndStatus.UNKNOWN, "not_checked"
        if to_number is not None:
            is_test = await self._exists(
                select(TestNumber.id).where(
                    TestNumber.tenant_id == tenant, TestNumber.e164 == to_number
                )
            )
            on_dnc = await self._exists(
                select(DoNotCallEntry.id).where(
                    DoNotCallEntry.tenant_id == tenant, DoNotCallEntry.phone == to_number
                )
            )
            rows = await self._session.scalars(
                select(Consent).where(Consent.tenant_id == tenant, Consent.phone == to_number)
            )
            consents = tuple(
                ConsentFact(
                    kind=ConsentKind(c.kind),
                    purpose=CallPurpose(c.purpose),
                    obtained_at=c.obtained_at,
                    expires_at=c.expires_at,
                    revoked=c.revoked_at is not None,
                )
                for c in rows
            )
            calls_today = await self._outbound_calls_since(to_number, self._local_midnight(now))
            calls_week = await self._outbound_calls_since(to_number, now - timedelta(days=7))
            if not (self._mode == TelephonyMode.TEST and is_test):
                lookup = await self._dnd.lookup(to_number, now=now)
                dnd, dnd_source = lookup.status, lookup.source
        numbers = await self._session.scalars(
            select(PhoneNumber).where(PhoneNumber.tenant_id == tenant)
        )
        caller_ids = tuple(
            CallerIdFact(
                e164=n.e164,
                purpose=CallPurpose(n.purpose),
                dlt_registered=n.dlt_registered,
                active=n.active,
            )
            for n in numbers
        )
        facts = GateFacts(
            mode=self._mode,
            purpose=purpose,
            to_number=to_number,
            is_test_number=is_test,
            lead_status=lead.status,
            lead_interest=lead.interest,
            on_do_not_call=on_dnc,
            consents=consents,
            dnd=dnd,
            calls_today=calls_today,
            calls_this_week=calls_week,
            caller_ids=caller_ids,
        )
        recorded: dict[str, object] = {
            "to_number": to_number,
            "is_test_number": is_test,
            "lead_status": lead.status,
            "lead_interest": lead.interest,
            "on_do_not_call": on_dnc,
            "consents": [
                {
                    "kind": c.kind.value,
                    "purpose": c.purpose.value,
                    "obtained_at": c.obtained_at.isoformat(),
                    "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                    "revoked": c.revoked,
                }
                for c in consents
            ],
            "dnd": dnd.value,
            "dnd_source": dnd_source,
            "calls_today": calls_today,
            "calls_this_week": calls_week,
            "caller_ids": [c.e164 for c in caller_ids if c.active],
            "evaluated_at": now.isoformat(),
            "local_time": now.astimezone(ZoneInfo(self._pack.timezone)).isoformat(),
        }
        return facts, recorded

    def _record(
        self,
        lead: Lead,
        purpose: CallPurpose,
        facts: GateFacts,
        recorded: dict[str, object],
        outcome: GateOutcome,
        requested_by: uuid.UUID | None,
    ) -> ComplianceDecision:
        return ComplianceDecision(
            id=uuid.uuid4(),
            tenant_id=self._tenant_id,
            lead_id=lead.id,
            requested_by_user_id=requested_by,
            action=OUTBOUND_CALL,
            purpose=purpose,
            to_number=facts.to_number,
            from_number=outcome.from_number if outcome.allowed else None,
            mode=self._mode,
            policy_pack=self._pack.name,
            policy_version=self._pack.version,
            policy_version_id=self._pack.version_id,
            checks=[c.as_dict() for c in outcome.checks],
            facts=recorded,
            decision=GateDecision.ALLOW if outcome.allowed else GateDecision.BLOCK,
            reason_code=outcome.reason_code,
        )

    async def _exists(self, query: object) -> bool:
        return (await self._session.scalar(query)) is not None  # type: ignore[call-overload]

    async def _campaign_fact(
        self, campaign: Campaign | None, lead: Lead, now: datetime
    ) -> CampaignFact | None:
        if campaign is None:
            return None
        base = (
            select(func.count())
            .select_from(Call)
            .where(
                Call.tenant_id == self._tenant_id,
                Call.direction == CallDirection.OUTBOUND,
                Call.campaign_id == campaign.id,
            )
        )
        attempts = await self._session.scalar(base.where(Call.lead_id == lead.id))
        today = await self._session.scalar(base.where(Call.created_at >= self._local_midnight(now)))
        return CampaignFact(
            status=campaign.status,
            purpose=CallPurpose(campaign.purpose),
            starts_on=campaign.starts_on,
            ends_on=campaign.ends_on,
            window_start=campaign.window_start,
            window_end=campaign.window_end,
            max_attempts_per_lead=campaign.max_attempts_per_lead,
            attempts_for_lead=int(attempts or 0),
            daily_call_cap=campaign.daily_call_cap,
            calls_today=int(today or 0),
        )

    def _local_midnight(self, now: datetime) -> datetime:
        return (
            now.astimezone(ZoneInfo(self._pack.timezone))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
        )

    async def _outbound_calls_since(self, to_number: str, since: datetime) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Call)
            .where(
                Call.tenant_id == self._tenant_id,
                Call.direction == CallDirection.OUTBOUND,
                Call.to_number == to_number,
                Call.created_at >= since,
            )
        )
        return int(count or 0)


def effective_policy_json(pack: PolicyPack) -> dict[str, object]:
    """The rules the decision was taken under (after the tenant's tightening), as JSON."""
    rules: dict[str, object] = {}
    for item in dataclasses.fields(pack):
        value = getattr(pack, item.name)
        if item.name == "version_id":
            value = str(value) if value else None
        elif item.name == "caller_id_prefixes":
            value = {str(k): list(v) for k, v in value.items()}
        elif isinstance(value, tuple):
            value = list(value)
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        rules[item.name] = value
    return rules
