"""Built-in calendar: bookable slots from a tenant's working hours minus booked appointments.

External calendars (Google, Outlook) can later sit behind the same tool interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.sales.models import Appointment, AppointmentStatus, SchedulingSettings


@dataclass(frozen=True)
class Hours:
    timezone: str = "Asia/Kolkata"
    work_days: tuple[int, ...] = (0, 1, 2, 3, 4)  # Monday-Friday
    day_start_minute: int = 10 * 60
    day_end_minute: int = 18 * 60
    slot_minutes: int = 30
    min_notice_minutes: int = 120
    horizon_days: int = 14


async def hours_for(session: AsyncSession, tenant_id: uuid.UUID) -> Hours:
    row = await session.scalar(
        select(SchedulingSettings).where(SchedulingSettings.tenant_id == tenant_id)
    )
    if row is None:
        return Hours()
    return Hours(
        timezone=row.timezone,
        work_days=tuple(row.work_days),
        day_start_minute=row.day_start_minute,
        day_end_minute=row.day_end_minute,
        slot_minutes=row.slot_minutes,
        min_notice_minutes=row.min_notice_minutes,
        horizon_days=row.horizon_days,
    )


def candidate_slots(hours: Hours, *, now: datetime, first_day: date, days: int) -> list[datetime]:
    """Every slot start within working hours, notice period and booking horizon (UTC)."""
    zone = ZoneInfo(hours.timezone)
    earliest = now + timedelta(minutes=hours.min_notice_minutes)
    latest = now + timedelta(days=hours.horizon_days)
    slots: list[datetime] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        if day.weekday() not in hours.work_days:
            continue
        minute = hours.day_start_minute
        while minute + hours.slot_minutes <= hours.day_end_minute:
            local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=zone)
            start = local.astimezone(UTC)
            if earliest <= start <= latest:
                slots.append(start)
            minute += hours.slot_minutes
    return slots


async def booked_starts(
    session: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> set[datetime]:
    rows = await session.scalars(
        select(Appointment.starts_at).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status == AppointmentStatus.BOOKED,
            Appointment.starts_at >= start,
            Appointment.starts_at < end,
        )
    )
    return {r.astimezone(UTC) for r in rows}


async def free_slots(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    hours: Hours,
    *,
    now: datetime,
    first_day: date,
    days: int,
) -> list[datetime]:
    candidates = candidate_slots(hours, now=now, first_day=first_day, days=days)
    if not candidates:
        return []
    taken = await booked_starts(
        session, tenant_id, candidates[0], candidates[-1] + timedelta(minutes=1)
    )
    return [slot for slot in candidates if slot not in taken]


def spoken(slot: datetime, hours: Hours) -> str:
    """How a person would say the slot, in the tenant's time zone."""
    local = slot.astimezone(ZoneInfo(hours.timezone))
    return local.strftime("%A %d %B, %I:%M %p").replace(" 0", " ")
