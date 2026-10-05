"""Engine, sessions and the per-transaction tenant context used by row-level security.

Tenant-owned tables carry Postgres row-level security policies that compare each row's
``tenant_id`` with the transaction-local setting ``app.tenant_id``. The setting is applied with
``set_config(..., is_local => true)``, so it ends with the transaction and can never leak to the
next request that reuses the pooled connection. A transaction with no tenant context sees no
tenant-owned rows at all.

The application must connect as a role that is neither a superuser nor ``BYPASSRLS``: such
roles skip every policy. ``Database.check_role`` verifies this at startup.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aurevia.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

TENANT_SETTING = "app.tenant_id"
USER_SETTING = "app.user_id"


@dataclass(frozen=True)
class RoleCheck:
    role: str
    bypasses_rls: bool


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, echo=echo)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def check_role(self) -> RoleCheck:
        """Report whether the connected role would bypass row-level security."""
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT current_user, rolsuper OR rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
        return RoleCheck(role=str(row[0]), bypasses_rls=bool(row[1]))

    async def dispose(self) -> None:
        await self.engine.dispose()


async def _set_local(session: AsyncSession, name: str, value: uuid.UUID) -> None:
    await session.execute(select(func.set_config(name, str(value), True)))


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope the current transaction to one tenant. Call before touching tenant-owned rows."""
    await _set_local(session, TENANT_SETTING, tenant_id)


async def set_user_context(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Let the current transaction see one user's own memberships across tenants (login only)."""
    await _set_local(session, USER_SETTING, user_id)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request. Writers commit explicitly."""
    database: Database | None = request.app.state.database
    if database is None:
        raise ServiceUnavailableError("Database is not configured")
    async with database.sessionmaker() as session:
        yield session
