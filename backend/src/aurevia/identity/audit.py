"""Audit events for security-relevant actions. Never put secrets or tokens in ``details``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from aurevia.identity.models import AuditEvent
from aurevia.logging import request_id_var


def record_audit_event(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction; it commits (or rolls back) with it."""
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=request_id_var.get(),
            details=details or {},
        )
    )
