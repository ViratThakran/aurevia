"""Integration fixtures: a real PostgreSQL database per test session.

Set ``AUREVIA_TEST_DATABASE_URL`` to a server URL whose user may create databases and roles,
e.g. ``postgresql://admin:pw@localhost:5432/postgres``. Each session creates a throwaway
database and a throwaway application role (not superuser, no BYPASSRLS), runs the Alembic
migrations as the admin, and runs the app as the application role, exactly like production.
Without the variable these tests are skipped, unless ``AUREVIA_REQUIRE_DB_TESTS=1`` (CI), in
which case they fail.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url

from aurevia.main import create_app
from tests.conftest import TEST_JWT_SECRET, SettingsFactory

# Read at import time: the root conftest strips AUREVIA_* variables before each test.
_SERVER_URL = os.environ.get("AUREVIA_TEST_DATABASE_URL")
_REQUIRED = os.environ.get("AUREVIA_REQUIRE_DB_TESTS") == "1"

BACKEND_DIR = Path(__file__).resolve().parents[2]
TABLES = (
    "tenants, users, memberships, refresh_tokens, audit_events, agents, calls, usage_events,"
    " turn_metrics, leads, conversation_messages, lead_memories, lead_notes, objections,"
    " followups, scheduling_settings, appointments, handoffs, tool_executions, phone_numbers,"
    " test_numbers, consents, do_not_call, compliance_decisions, campaigns,"
    " tenant_compliance_settings, erasure_requests, custom_roles, invitations, tenant_plans,"
    " prices, campaign_leads"
)


@dataclass(frozen=True)
class PgEnv:
    admin_dsn: str  # superuser, test database: setup and assertions (bypasses RLS)
    owner_url: str  # SQLAlchemy URL for migrations
    app_url: str  # SQLAlchemy URL for the application role
    app_dsn: str  # asyncpg DSN for the application role
    app_role: str


def _dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def _execute(dsn: str, *statements: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        for statement in statements:
            await conn.execute(statement)
    finally:
        await conn.close()


async def _fetch(dsn: str, query: str, *args: Any) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(dsn)
    try:
        return list(await conn.fetch(query, *args))
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def pg() -> Iterator[PgEnv]:
    if not _SERVER_URL:
        if _REQUIRED:
            pytest.fail("AUREVIA_TEST_DATABASE_URL is required (AUREVIA_REQUIRE_DB_TESTS=1)")
        pytest.skip("AUREVIA_TEST_DATABASE_URL not set; skipping database tests")

    server = make_url(_SERVER_URL)
    suffix = secrets.token_hex(4)
    db_name, role = f"aurevia_test_{suffix}", f"aurevia_test_app_{suffix}"
    role_password = secrets.token_hex(16)

    asyncio.run(
        _execute(
            _dsn(server),
            f"CREATE DATABASE {db_name}",
            f"CREATE ROLE {role} LOGIN PASSWORD '{role_password}' NOSUPERUSER NOBYPASSRLS",
        )
    )
    test_db = server.set(database=db_name)
    app_db = test_db.set(username=role, password=role_password)
    env = PgEnv(
        admin_dsn=_dsn(test_db),
        owner_url=test_db.set(drivername="postgresql+asyncpg").render_as_string(
            hide_password=False
        ),
        app_url=app_db.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False),
        app_dsn=_dsn(app_db),
        app_role=role,
    )
    try:
        upgrade_to_head(env)
        yield env
    finally:
        asyncio.run(
            _execute(
                _dsn(server),
                f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)",
                f"DROP ROLE IF EXISTS {role}",
            )
        )


def alembic_config(env: PgEnv) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = env.owner_url
    config.attributes["app_role"] = env.app_role
    return config


def upgrade_to_head(env: PgEnv) -> None:
    command.upgrade(alembic_config(env), "head")


# TRUNCATE needs an exclusive lock on every table, so it waits for any connection a test left
# inside an open transaction. Without a limit it waits forever (CI stalled this way). With one,
# the test fails and names the connection that blocked it.
CLEANUP_LOCK_TIMEOUT = "20s"

_BLOCKERS = (
    "SELECT a.pid, a.usename, a.state, a.wait_event_type, a.xact_start, a.query_start, "
    "left(a.query, 200) AS query FROM pg_stat_activity a "
    "WHERE a.datname = current_database() AND a.pid <> pg_backend_pid() "
    "AND (a.state <> 'idle' OR a.xact_start IS NOT NULL) ORDER BY a.xact_start NULLS LAST"
)


async def _truncate_or_explain(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        try:
            await conn.execute(f"SET lock_timeout = '{CLEANUP_LOCK_TIMEOUT}'")
            await conn.execute(f"TRUNCATE {TABLES} CASCADE")
        except asyncpg.LockNotAvailableError:
            rows = await conn.fetch(_BLOCKERS)
            detail = "\n".join(str(dict(row)) for row in rows) or "(no open sessions found)"
            # Do not leave the database wedged for the tests that follow.
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND usename <> current_user"
            )
            pytest.fail(
                f"Cleanup waited {CLEANUP_LOCK_TIMEOUT} for a lock: a test left a database "
                f"connection open inside a transaction. Sessions at that moment:\n{detail}",
                pytrace=False,
            )
        await conn.execute("RESET lock_timeout")
        for statement in _RESET_POLICY_VERSIONS:
            await conn.execute(statement)
    finally:
        await conn.close()


@pytest.fixture
def db(pg: PgEnv) -> Iterator[PgEnv]:
    """The session database, emptied after each test."""
    yield pg
    asyncio.run(_truncate_or_explain(pg.admin_dsn))


# Policy versions are platform data that tests may publish, review or retire. Back to the
# seeded draft only (the guard trigger forbids this outside tests, by design).
_RESET_POLICY_VERSIONS = (
    "ALTER TABLE policy_versions DISABLE TRIGGER policy_versions_guard",
    "DELETE FROM policy_versions WHERE version <> 'india-2026-10-draft-1'",
    "UPDATE policy_versions SET status = 'draft', reviewed_at = NULL, reviewed_by = NULL, "
    "review_reference = NULL, retired_at = NULL",
    "ALTER TABLE policy_versions ENABLE TRIGGER policy_versions_guard",
)


def admin_fetch(env: PgEnv, query: str, *args: Any) -> list[asyncpg.Record]:
    return asyncio.run(_fetch(env.admin_dsn, query, *args))


def admin_execute(env: PgEnv, *statements: str) -> None:
    asyncio.run(_execute(env.admin_dsn, *statements))


@pytest.fixture
def api(db: PgEnv, make_settings: SettingsFactory) -> Iterator[TestClient]:
    settings = make_settings(
        database_url=db.app_url, jwt_secret=TEST_JWT_SECRET, database_app_role=db.app_role
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        yield client


# --- API helpers ---------------------------------------------------------------------


PASSWORD = "correct horse battery staple"  # test-only


def signup(client: TestClient, email: str, tenant_name: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "tenant_name": tenant_name},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def bearer(tokens: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def me(client: TestClient, tokens: dict[str, Any]) -> dict[str, Any]:
    response = client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def add_member(env: PgEnv, *, tenant_id: str, email: str, role: str) -> str:
    """Join an existing user to a tenant directly (no invite flow in Phase 1)."""
    rows = admin_fetch(
        env,
        "INSERT INTO memberships (id, tenant_id, user_id, role, status) "
        "SELECT gen_random_uuid(), $1::uuid, id, $3, 'active' FROM users WHERE email = $2 "
        "RETURNING id",
        tenant_id,
        email,
        role,
    )
    return str(rows[0]["id"])
