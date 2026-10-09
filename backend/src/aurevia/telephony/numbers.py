"""The tenant's caller-id / inbound numbers and its own test numbers (owners and admins)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.errors import ConflictError, NotFoundError
from aurevia.identity.audit import record_audit_event
from aurevia.telephony.models import PhoneNumber, TestNumber
from aurevia.telephony.schemas import PhoneNumberIn, PhoneNumberUpdate, TestNumberIn


class NumberService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def add_phone_number(self, body: PhoneNumberIn, actor: uuid.UUID) -> PhoneNumber:
        number = PhoneNumber(
            tenant_id=self._tenant_id,
            e164=body.e164,
            carrier=body.carrier,
            purpose=body.purpose,
            dlt_registered=body.dlt_registered,
            inbound_enabled=body.inbound_enabled,
            active=True,
        )
        self._session.add(number)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # One number belongs to one tenant; whose it is stays private.
            raise ConflictError(
                "This number is already registered", code="number_already_registered"
            ) from exc
        self._audit(actor, "phone_number.added", number.id, {"purpose": body.purpose.value})
        await self._session.commit()
        return number

    async def list_phone_numbers(self) -> list[PhoneNumber]:
        rows = await self._session.scalars(
            select(PhoneNumber)
            .where(PhoneNumber.tenant_id == self._tenant_id)
            .order_by(PhoneNumber.created_at)
        )
        return list(rows)

    async def update_phone_number(
        self, number_id: uuid.UUID, body: PhoneNumberUpdate, actor: uuid.UUID
    ) -> PhoneNumber:
        number = await self._session.scalar(
            select(PhoneNumber).where(
                PhoneNumber.id == number_id, PhoneNumber.tenant_id == self._tenant_id
            )
        )
        if number is None:
            raise NotFoundError("Phone number not found")
        changes = body.model_dump(exclude_none=True)
        for name, value in changes.items():
            setattr(number, name, value)
        if changes:
            self._audit(actor, "phone_number.updated", number.id, changes)
            await self._session.commit()
        return number

    async def add_test_number(
        self, body: TestNumberIn, actor: uuid.UUID, *, limit: int
    ) -> TestNumber:
        count = await self._session.scalar(
            select(func.count())
            .select_from(TestNumber)
            .where(TestNumber.tenant_id == self._tenant_id)
        )
        if int(count or 0) >= limit:
            raise ConflictError(
                f"At most {limit} test numbers are allowed", code="too_many_test_numbers"
            )
        number = TestNumber(
            tenant_id=self._tenant_id, e164=body.e164, label=body.label, added_by_user_id=actor
        )
        self._session.add(number)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "This test number is already registered", code="test_number_exists"
            ) from exc
        self._audit(actor, "test_number.added", number.id, {"label": body.label})
        await self._session.commit()
        return number

    async def list_test_numbers(self) -> list[TestNumber]:
        rows = await self._session.scalars(
            select(TestNumber)
            .where(TestNumber.tenant_id == self._tenant_id)
            .order_by(TestNumber.created_at)
        )
        return list(rows)

    async def remove_test_number(self, number_id: uuid.UUID, actor: uuid.UUID) -> None:
        number = await self._session.scalar(
            select(TestNumber).where(
                TestNumber.id == number_id, TestNumber.tenant_id == self._tenant_id
            )
        )
        if number is None:
            raise NotFoundError("Test number not found")
        await self._session.delete(number)
        self._audit(actor, "test_number.removed", number_id, None)
        await self._session.commit()

    def _audit(
        self,
        actor: uuid.UUID,
        action: str,
        target_id: uuid.UUID,
        details: dict[str, object] | None,
    ) -> None:
        record_audit_event(
            self._session,
            tenant_id=self._tenant_id,
            actor_user_id=actor,
            action=action,
            target_type=action.split(".")[0],
            target_id=target_id,
            details=details,
        )
