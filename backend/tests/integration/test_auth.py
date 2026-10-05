from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from tests.conftest import TEST_JWT_SECRET
from tests.integration.conftest import (
    PASSWORD,
    PgEnv,
    add_member,
    admin_execute,
    admin_fetch,
    bearer,
    me,
    signup,
)


def _login(client: TestClient, email: str, password: str = PASSWORD, **extra: str) -> object:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})


def test_signup_creates_tenant_owner_and_audit_event(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "Owner@Example.com", "Acme Brokers")
    assert tokens["token_type"] == "bearer"
    profile = me(api, tokens)
    assert profile["email"] == "owner@example.com"  # stored lower-cased
    assert profile["role"] == "owner"
    assert profile["tenant"]["name"] == "Acme Brokers"

    events = admin_fetch(db, "SELECT action, tenant_id::text FROM audit_events")
    assert [(e["action"], e["tenant_id"]) for e in events] == [
        ("tenant.created", profile["tenant"]["id"])
    ]
    stored = admin_fetch(db, "SELECT password_hash FROM users")[0]["password_hash"]
    assert stored.startswith("$argon2") and PASSWORD not in stored


def test_signup_rejects_duplicate_email_case_insensitively(api: TestClient, db: PgEnv) -> None:
    signup(api, "dup@example.com", "One")
    response = api.post(
        "/api/v1/auth/signup",
        json={"email": "DUP@example.com", "password": PASSWORD, "tenant_name": "Two"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_signup_rejects_short_password_without_echoing_it(api: TestClient, db: PgEnv) -> None:
    response = api.post(
        "/api/v1/auth/signup",
        json={"email": "a@example.com", "password": "short-pw", "tenant_name": "T"},
    )
    assert response.status_code == 422
    assert "short-pw" not in response.text


def test_login_succeeds_and_records_audit(api: TestClient, db: PgEnv) -> None:
    signup(api, "user@example.com", "Acme")
    response = _login(api, "user@example.com")
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert me(api, response.json())["email"] == "user@example.com"  # type: ignore[attr-defined]
    actions = [r["action"] for r in admin_fetch(db, "SELECT action FROM audit_events")]
    assert "user.logged_in" in actions


def test_wrong_password_and_unknown_email_look_identical(api: TestClient, db: PgEnv) -> None:
    signup(api, "user@example.com", "Acme")
    wrong = _login(api, "user@example.com", "not the right password")
    unknown = _login(api, "nobody@example.com")
    for response in (wrong, unknown):
        assert response.status_code == 401  # type: ignore[attr-defined]
        assert response.headers["WWW-Authenticate"] == "Bearer"  # type: ignore[attr-defined]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]  # type: ignore[attr-defined]


def test_user_in_two_tenants_must_choose(api: TestClient, db: PgEnv) -> None:
    signup(api, "multi@example.com", "First")
    other = signup(api, "boss@example.com", "Second")
    second_id = me(api, other)["tenant"]["id"]
    add_member(db, tenant_id=second_id, email="multi@example.com", role="member")

    response = _login(api, "multi@example.com")
    assert response.status_code == 409  # type: ignore[attr-defined]
    error = response.json()["error"]  # type: ignore[attr-defined]
    assert error["code"] == "tenant_selection_required"
    assert {t["name"] for t in error["details"]} == {"First", "Second"}

    chosen = _login(api, "multi@example.com", tenant_id=second_id)
    assert chosen.status_code == 200  # type: ignore[attr-defined]
    profile = me(api, chosen.json())  # type: ignore[attr-defined]
    assert profile["tenant"]["id"] == second_id
    assert profile["role"] == "member"


def test_login_to_a_tenant_without_membership_is_refused(api: TestClient, db: PgEnv) -> None:
    signup(api, "a@example.com", "Alpha")
    b_tenant = me(api, signup(api, "b@example.com", "Beta"))["tenant"]["id"]
    response = _login(api, "a@example.com", tenant_id=b_tenant)
    assert response.status_code == 403  # type: ignore[attr-defined]


def test_protected_endpoint_requires_a_valid_token(api: TestClient, db: PgEnv) -> None:
    assert api.get("/api/v1/auth/me").status_code == 401
    assert api.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_expired_access_token_is_rejected(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "user@example.com", "Acme")
    claims = jwt.decode(tokens["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    past = datetime.now(UTC) - timedelta(hours=1)
    claims.update(iat=past, exp=past + timedelta(minutes=5))
    expired = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    response = api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_refresh_rotates_and_reuse_revokes_the_whole_session(api: TestClient, db: PgEnv) -> None:
    first = signup(api, "user@example.com", "Acme")
    rotated = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    me(api, second)

    # The old token is presented again: treated as stolen, every token of the login dies.
    replay = api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    after = api.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert after.status_code == 401


def test_expired_refresh_token_is_rejected(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "user@example.com", "Acme")
    admin_execute(db, "UPDATE refresh_tokens SET expires_at = now() - interval '1 minute'")
    response = api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_only_token_hashes_are_stored(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "user@example.com", "Acme")
    stored = admin_fetch(db, "SELECT token_hash FROM refresh_tokens")[0]["token_hash"]
    assert stored != tokens["refresh_token"] and len(stored) == 64


def test_logout_revokes_the_session(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "user@example.com", "Acme")
    assert (
        api.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}).status_code
        == 204
    )
    response = api.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


def test_removed_member_loses_access_immediately(api: TestClient, db: PgEnv) -> None:
    owner = signup(api, "owner@example.com", "Acme")
    tenant_id = me(api, owner)["tenant"]["id"]
    signup(api, "staff@example.com", "Staff Own")
    membership_id = add_member(db, tenant_id=tenant_id, email="staff@example.com", role="member")
    staff = _login(api, "staff@example.com", tenant_id=tenant_id).json()  # type: ignore[attr-defined]
    me(api, staff)

    removed = api.delete(f"/api/v1/tenant/members/{membership_id}", headers=bearer(owner))
    assert removed.status_code == 204
    # Access token still unexpired, but the membership is re-checked on every request.
    assert api.get("/api/v1/auth/me", headers=bearer(staff)).status_code == 401
    refresh = api.post("/api/v1/auth/refresh", json={"refresh_token": staff["refresh_token"]})
    assert refresh.status_code == 401


def test_disabled_user_cannot_sign_in_or_use_tokens(api: TestClient, db: PgEnv) -> None:
    tokens = signup(api, "user@example.com", "Acme")
    admin_execute(db, "UPDATE users SET status = 'disabled'")
    assert _login(api, "user@example.com").status_code == 401  # type: ignore[attr-defined]
    assert api.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401
