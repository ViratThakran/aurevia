from __future__ import annotations

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from aurevia.config import Settings
from aurevia.main import UnsafeDatabaseRoleError, create_app
from tests.conftest import TEST_JWT_SECRET
from tests.integration.conftest import PgEnv, admin_fetch, alembic_config


def test_models_match_migrations(db: PgEnv) -> None:
    """Fails if a model changed without a migration (alembic autogenerate finds a diff)."""
    command.check(alembic_config(db))


def test_rls_is_forced_on_tenant_owned_tables(db: PgEnv) -> None:
    rows = admin_fetch(
        db,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname IN ('tenants', 'memberships', 'audit_events') ORDER BY relname",
    )
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("audit_events", True, True),
        ("memberships", True, True),
        ("tenants", True, True),
    ]


def test_readiness_reports_database(db: PgEnv) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=db.app_url,
        jwt_secret=TEST_JWT_SECRET,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok"}


def test_production_refuses_a_role_that_bypasses_rls(db: PgEnv) -> None:
    superuser_url = make_url(db.owner_url).render_as_string(hide_password=False)
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url=superuser_url,
        jwt_secret=TEST_JWT_SECRET,
    )
    with pytest.raises(UnsafeDatabaseRoleError), TestClient(create_app(settings)):
        pass
