"""Row-level security, tested below the application: raw SQL as the application role."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import PgEnv, me, signup


def _as_app(env: PgEnv, statements: list[tuple[str, tuple[Any, ...]]]) -> list[Any]:
    """Run statements in ONE transaction as the application role; return each result."""

    async def run() -> list[Any]:
        conn = await asyncpg.connect(env.app_dsn)
        try:
            async with conn.transaction():
                return [await conn.fetch(sql, *args) for sql, args in statements]
        finally:
            await conn.close()

    return asyncio.run(run())


def _tenants(api: TestClient) -> tuple[str, str]:
    a = me(api, signup(api, "a@example.com", "Alpha"))["tenant"]["id"]
    b = me(api, signup(api, "b@example.com", "Beta"))["tenant"]["id"]
    return a, b


SET_TENANT = "SELECT set_config('app.tenant_id', $1, true)"


def test_no_tenant_context_sees_no_rows(api: TestClient, db: PgEnv) -> None:
    _tenants(api)
    results = _as_app(
        db,
        [
            ("SELECT * FROM tenants", ()),
            ("SELECT * FROM memberships", ()),
            ("SELECT * FROM audit_events", ()),
        ],
    )
    assert all(len(rows) == 0 for rows in results)


def test_tenant_context_sees_only_that_tenant(api: TestClient, db: PgEnv) -> None:
    a, _ = _tenants(api)
    _, tenants, memberships, audit = _as_app(
        db,
        [
            (SET_TENANT, (a,)),
            ("SELECT id::text FROM tenants", ()),
            ("SELECT tenant_id::text FROM memberships", ()),
            ("SELECT tenant_id::text FROM audit_events", ()),
        ],
    )
    assert [r[0] for r in tenants] == [a]
    assert {r[0] for r in memberships} == {a}
    assert {r[0] for r in audit} == {a}


def test_explicit_filter_cannot_reach_another_tenant(api: TestClient, db: PgEnv) -> None:
    a, b = _tenants(api)
    _, rows = _as_app(
        db,
        [(SET_TENANT, (a,)), ("SELECT * FROM memberships WHERE tenant_id = $1::uuid", (b,))],
    )
    assert rows == []


def test_cannot_write_into_another_tenant(api: TestClient, db: PgEnv) -> None:
    a, b = _tenants(api)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        _as_app(
            db,
            [
                (SET_TENANT, (a,)),
                (
                    "INSERT INTO audit_events (id, tenant_id, action, details) "
                    "VALUES (gen_random_uuid(), $1::uuid, 'forged', '{}')",
                    (b,),
                ),
            ],
        )


def test_update_cannot_move_rows_between_tenants(api: TestClient, db: PgEnv) -> None:
    a, b = _tenants(api)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        _as_app(
            db,
            [(SET_TENANT, (a,)), ("UPDATE memberships SET tenant_id = $1::uuid", (b,))],
        )


def test_context_does_not_outlive_the_transaction(api: TestClient, db: PgEnv) -> None:
    a, _ = _tenants(api)

    async def run() -> tuple[int, int]:
        conn = await asyncpg.connect(db.app_dsn)
        try:
            async with conn.transaction():
                await conn.execute(SET_TENANT, a)
                inside = len(await conn.fetch("SELECT * FROM memberships"))
            after = len(await conn.fetch("SELECT * FROM memberships"))  # same connection
            return inside, after
        finally:
            await conn.close()

    inside, after = asyncio.run(run())
    assert (inside, after) == (1, 0)


def test_app_role_has_no_delete_and_audit_is_append_only(api: TestClient, db: PgEnv) -> None:
    a, _ = _tenants(api)
    for statement in ("DELETE FROM memberships", "UPDATE audit_events SET action = 'x'"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            _as_app(db, [(SET_TENANT, (a,)), (statement, ())])


def test_app_role_does_not_bypass_rls(db: PgEnv) -> None:
    (rows,) = _as_app(
        db, [("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user", ())]
    )
    assert (rows[0]["rolsuper"], rows[0]["rolbypassrls"]) == (False, False)
