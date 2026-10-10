"""The Phase 5 sales tools. Each validates its input, applies its business rules and writes
only through the session it is given; the framework commits and audits."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from aurevia.compliance.models import DoNotCallReason
from aurevia.compliance.phone import normalize_e164
from aurevia.compliance.service import DoNotCallService
from aurevia.memory.models import Lead, LeadInterest
from aurevia.sales.models import (
    Appointment,
    AppointmentStatus,
    Followup,
    FollowupChannel,
    Handoff,
    HandoffUrgency,
    LeadNote,
    Objection,
    ObjectionCategory,
)
from aurevia.sales.scheduling import free_slots, hours_for, spoken
from aurevia.sales.state import InvalidTransitionError, SalesState, transition
from aurevia.tools.framework import Tool, ToolContext, ToolOutcome, ToolRegistry


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _lead(ctx: ToolContext) -> Lead:
    assert ctx.lead is not None  # noqa: S101 - the framework enforces requires_lead
    return ctx.lead


# --- Sales state ---------------------------------------------------------------------------

AgentStage = Literal["discovery", "qualification", "pitch", "objection", "next_step", "follow_up"]


class SetStageArgs(_Args):
    stage: AgentStage


class SetStage(Tool[SetStageArgs]):
    name = "set_stage"
    description = (
        "Move the conversation to another sales stage when it has clearly changed, e.g. to "
        "'pitch' once needs are understood or 'objection' when the prospect pushes back."
    )
    args_model = SetStageArgs
    record_only = True
    requires_lead = False

    async def run(self, ctx: ToolContext, args: SetStageArgs) -> ToolOutcome:
        current = SalesState(ctx.call.sales_state)
        try:
            new = transition(current, SalesState(args.stage))
        except InvalidTransitionError:
            return ToolOutcome.rejected(
                "transition_not_allowed",
                f"Cannot move from {current.value} to {args.stage}.",
                stage=current.value,
            )
        ctx.call.sales_state = new
        return ToolOutcome.ok(f"Stage is now {new.value}.", stage=new.value)


# --- Lead facts ----------------------------------------------------------------------------


class QualifyArgs(_Args):
    need: str | None = Field(default=None, max_length=300)
    timeline: str | None = Field(default=None, max_length=200)
    budget: str | None = Field(default=None, max_length=200)
    decision_maker: bool | None = None
    company_size: int | None = Field(default=None, ge=1, le=10_000_000)

    @model_validator(mode="after")
    def _at_least_one(self) -> QualifyArgs:
        if not self.model_dump(exclude_none=True):
            raise ValueError("give at least one qualification field")
        return self


class QualifyLead(Tool[QualifyArgs]):
    name = "qualify_lead"
    description = (
        "Record qualification answers the prospect gave: their need, timeline, budget, whether "
        "they decide, company size. Only what they actually said."
    )
    args_model = QualifyArgs
    record_only = True

    async def run(self, ctx: ToolContext, args: QualifyArgs) -> ToolOutcome:
        lead = _lead(ctx)
        lead.qualification = {**lead.qualification, **args.model_dump(exclude_none=True)}
        return ToolOutcome.ok("Qualification saved.", qualification=lead.qualification)


class InterestArgs(_Args):
    note: str | None = Field(default=None, max_length=500)


class MarkInterested(Tool[InterestArgs]):
    name = "mark_interested"
    description = "Record that the prospect said they are interested."
    args_model = InterestArgs
    record_only = True

    async def run(self, ctx: ToolContext, args: InterestArgs) -> ToolOutcome:
        lead = _lead(ctx)
        lead.interest, lead.interest_reason = LeadInterest.INTERESTED, args.note
        return ToolOutcome.ok("Marked as interested.")


class NotInterestedArgs(_Args):
    reason: str = Field(min_length=2, max_length=500)


class MarkNotInterested(Tool[NotInterestedArgs]):
    name = "mark_not_interested"
    description = "Record that the prospect clearly said they are not interested, and why."
    args_model = NotInterestedArgs
    record_only = True

    async def run(self, ctx: ToolContext, args: NotInterestedArgs) -> ToolOutcome:
        lead = _lead(ctx)
        lead.interest, lead.interest_reason = LeadInterest.NOT_INTERESTED, args.reason
        return ToolOutcome.ok("Marked as not interested.")


class ObjectionArgs(_Args):
    category: ObjectionCategory
    detail: str = Field(min_length=2, max_length=500)


class LogObjection(Tool[ObjectionArgs]):
    name = "log_objection"
    description = "Record an objection the prospect raised (price, timing, competitor, trust...)."
    args_model = ObjectionArgs
    record_only = True

    async def run(self, ctx: ToolContext, args: ObjectionArgs) -> ToolOutcome:
        ctx.session.add(
            Objection(
                tenant_id=ctx.tenant_id,
                lead_id=_lead(ctx).id,
                call_id=ctx.call.id,
                category=args.category,
                detail=args.detail,
            )
        )
        return ToolOutcome.ok("Objection logged.")


class NoteArgs(_Args):
    text: str = Field(min_length=2, max_length=1000)


class AddNote(Tool[NoteArgs]):
    name = "add_note"
    description = "Save a short note for the sales team about this prospect."
    args_model = NoteArgs
    record_only = True

    async def run(self, ctx: ToolContext, args: NoteArgs) -> ToolOutcome:
        ctx.session.add(
            LeadNote(
                tenant_id=ctx.tenant_id, lead_id=_lead(ctx).id, call_id=ctx.call.id, text=args.text
            )
        )
        return ToolOutcome.ok("Note saved.")


# --- Follow-ups ----------------------------------------------------------------------------


class FollowupArgs(_Args):
    due_at: AwareDatetime = Field(description="ISO 8601 date-time with time zone offset")
    channel: FollowupChannel
    note: str = Field(min_length=2, max_length=500)


class ScheduleFollowup(Tool[FollowupArgs]):
    name = "schedule_followup"
    description = (
        "Schedule a follow-up (a call back, email or WhatsApp) the prospect agreed to. "
        "due_at must be in the future, within 90 days."
    )
    args_model = FollowupArgs

    async def run(self, ctx: ToolContext, args: FollowupArgs) -> ToolOutcome:
        due = args.due_at.astimezone(UTC)
        if due < ctx.now + timedelta(minutes=5):
            return ToolOutcome.rejected("in_the_past", "That time has already passed.")
        if due > ctx.now + timedelta(days=90):
            return ToolOutcome.rejected("too_far", "Follow-ups can be at most 90 days ahead.")
        followup = Followup(
            tenant_id=ctx.tenant_id,
            lead_id=_lead(ctx).id,
            call_id=ctx.call.id,
            due_at=due,
            channel=args.channel,
            note=args.note,
        )
        ctx.session.add(followup)
        await ctx.session.flush()
        return ToolOutcome.ok(
            "Follow-up scheduled.", followup_id=str(followup.id), due_at=due.isoformat()
        )


# --- Calendar ------------------------------------------------------------------------------


class SlotsArgs(_Args):
    from_date: date | None = Field(default=None, description="First day to look at (YYYY-MM-DD)")
    days: int = Field(default=3, ge=1, le=7)


class GetAvailableSlots(Tool[SlotsArgs]):
    name = "get_available_slots"
    description = (
        "List free meeting times. Always call this before offering or booking a time; never "
        "guess availability."
    )
    args_model = SlotsArgs
    requires_lead = False

    async def run(self, ctx: ToolContext, args: SlotsArgs) -> ToolOutcome:
        hours = await hours_for(ctx.session, ctx.tenant_id)
        today = ctx.now.date()
        # Models often guess a past date (even the wrong year). Searching the past finds
        # nothing and invites retries, each a full model round of silence on the call: look
        # from today instead, and say so.
        moved = args.from_date is not None and args.from_date < today
        first = today if args.from_date is None or moved else args.from_date
        slots = await free_slots(
            ctx.session, ctx.tenant_id, hours, now=ctx.now, first_day=first, days=args.days
        )
        offered = slots[:6]
        note = {"today": today.isoformat()}
        if moved:
            note["note"] = f"{args.from_date} is in the past; searched from today instead."
        if not offered:
            return ToolOutcome.ok("No free times in that range.", slots=[], **note)
        return ToolOutcome.ok(
            "Free times found. Offer one or two, in words.",
            slots=[{"start": s.isoformat(), "spoken": spoken(s, hours)} for s in offered],
            time_zone=hours.timezone,
            **note,
        )


class BookArgs(_Args):
    start: AwareDatetime = Field(description="A 'start' value returned by get_available_slots")


class BookMeeting(Tool[BookArgs]):
    name = "book_meeting"
    description = (
        "Book a meeting at a time from get_available_slots that the prospect accepted. "
        "Only say it is booked if this returns ok."
    )
    args_model = BookArgs

    async def run(self, ctx: ToolContext, args: BookArgs) -> ToolOutcome:
        lead = _lead(ctx)
        if lead.interest == LeadInterest.NOT_INTERESTED:
            return ToolOutcome.rejected(
                "lead_not_interested", "This prospect is marked not interested."
            )
        hours = await hours_for(ctx.session, ctx.tenant_id)
        start = args.start.astimezone(UTC)
        free = await free_slots(
            ctx.session,
            ctx.tenant_id,
            hours,
            now=ctx.now,
            first_day=start.date() - timedelta(days=1),
            days=3,
        )
        if start not in free:
            return ToolOutcome.rejected(
                "slot_unavailable", "That time is not available. Check free times again."
            )
        appointment = Appointment(
            tenant_id=ctx.tenant_id,
            lead_id=lead.id,
            call_id=ctx.call.id,
            starts_at=start,
            ends_at=start + timedelta(minutes=hours.slot_minutes),
            status=AppointmentStatus.BOOKED,
        )
        ctx.session.add(appointment)
        await ctx.session.flush()  # the unique index rejects a concurrent double booking here
        return ToolOutcome.ok(
            "Meeting booked.",
            appointment_id=str(appointment.id),
            start=start.isoformat(),
            spoken=spoken(start, hours),
        )


class CancelArgs(_Args):
    appointment_id: uuid.UUID | None = Field(
        default=None, description="Omit if the prospect has exactly one upcoming meeting"
    )


class CancelMeeting(Tool[CancelArgs]):
    name = "cancel_meeting"
    description = "Cancel this prospect's upcoming meeting when they ask to."
    args_model = CancelArgs

    async def run(self, ctx: ToolContext, args: CancelArgs) -> ToolOutcome:
        query = select(Appointment).where(
            Appointment.tenant_id == ctx.tenant_id,
            Appointment.lead_id == _lead(ctx).id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.starts_at > ctx.now,
        )
        if args.appointment_id:
            query = query.where(Appointment.id == args.appointment_id)
        upcoming = (await ctx.session.scalars(query)).all()
        if not upcoming:
            return ToolOutcome.rejected("not_found", "There is no upcoming meeting to cancel.")
        if len(upcoming) > 1:
            return ToolOutcome.rejected(
                "ambiguous",
                "There are several upcoming meetings; ask which one.",
                meetings=[
                    {"appointment_id": str(a.id), "start": a.starts_at.isoformat()}
                    for a in upcoming
                ],
            )
        upcoming[0].status = AppointmentStatus.CANCELLED
        return ToolOutcome.ok("Meeting cancelled.", appointment_id=str(upcoming[0].id))


# --- Human handoff -------------------------------------------------------------------------


class HandoffArgs(_Args):
    reason: str = Field(min_length=2, max_length=500)
    urgency: HandoffUrgency = HandoffUrgency.NORMAL


class FlagForHandoff(Tool[HandoffArgs]):
    name = "flag_for_handoff"
    description = (
        "Ask a human colleague to take over: the prospect asks for a person, the question needs "
        "information you do not have, it is a large opportunity, or it is sensitive."
    )
    args_model = HandoffArgs
    record_only = True
    requires_lead = False

    async def run(self, ctx: ToolContext, args: HandoffArgs) -> ToolOutcome:
        ctx.session.add(
            Handoff(
                tenant_id=ctx.tenant_id,
                lead_id=ctx.lead.id if ctx.lead else None,
                call_id=ctx.call.id,
                reason=args.reason,
                urgency=args.urgency,
            )
        )
        # The request is recorded either way; the stage only moves if the machine allows it.
        with contextlib.suppress(InvalidTransitionError):
            ctx.call.sales_state = transition(
                SalesState(ctx.call.sales_state), SalesState.HUMAN_HANDOFF
            )
        return ToolOutcome.ok("A colleague has been asked to follow up personally.")


# --- Compliance (Phase 6) ------------------------------------------------------------------


class DoNotCallArgs(_Args):
    note: str | None = Field(default=None, max_length=300)


class RequestDoNotCall(Tool[DoNotCallArgs]):
    name = "request_do_not_call"
    description = (
        "The prospect asked not to be called again. Adds their number to the do-not-call list; "
        "after this, no call to that number is ever placed. Use it whenever they ask, even "
        "politely or in passing."
    )
    args_model = DoNotCallArgs
    requires_lead = False
    record_only = True

    async def run(self, ctx: ToolContext, args: DoNotCallArgs) -> ToolOutcome:
        call = ctx.call
        # The line actually in use: the number we dialed, or the number that called us.
        phone = call.to_number if call.direction == "outbound" else call.from_number
        if phone is None and ctx.lead is not None:
            phone = normalize_e164(ctx.lead.phone)
        if phone is None and ctx.lead is None:
            return ToolOutcome.rejected(
                "no_phone_number",
                "There is no phone number or lead for this conversation, so nothing could be "
                "recorded.",
            )
        if phone is not None:
            await DoNotCallService(ctx.session, ctx.tenant_id).add(
                phone, DoNotCallReason.PROSPECT_REQUEST, note=args.note, source_call_id=call.id
            )
        if ctx.lead is not None:
            # The gate never calls a lead marked not interested, with or without a number.
            ctx.lead.interest = LeadInterest.NOT_INTERESTED
            ctx.lead.interest_reason = "Asked not to be called again"
        return ToolOutcome.ok("They will not be called again.")


def default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            SetStage(),
            QualifyLead(),
            MarkInterested(),
            MarkNotInterested(),
            LogObjection(),
            AddNote(),
            ScheduleFollowup(),
            GetAvailableSlots(),
            BookMeeting(),
            CancelMeeting(),
            FlagForHandoff(),
            RequestDoNotCall(),
        ]
    )
