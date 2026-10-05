"""Tenant A must never read, change or detect tenant B's data through the API."""

from __future__ import annotations

import uuid

import jwt
from fastapi.testclient import TestClient

from tests.conftest import TEST_JWT_SECRET
from tests.integration.conftest import PgEnv, add_member, admin_fetch, bearer, me, signup


def _two_tenants(api: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    return signup(api, "a@example.com", "Tenant A"), signup(api, "b@example.com", "Tenant B")


def _membership_id(db: PgEnv, email: str) -> str:
    rows = admin_fetch(
        db,
        "SELECT m.id::text FROM memberships m JOIN users u ON u.id = m.user_id WHERE u.email = $1",
        email,
    )
    return str(rows[0]["id"])


def test_member_list_shows_only_own_tenant(api: TestClient, db: PgEnv) -> None:
    a, _ = _two_tenants(api)
    members = api.get("/api/v1/tenant/members", headers=bearer(a)).json()
    assert [m["email"] for m in members] == ["a@example.com"]


def test_cannot_change_or_remove_another_tenants_member(api: TestClient, db: PgEnv) -> None:
    a, _ = _two_tenants(api)
    b_membership = _membership_id(db, "b@example.com")

    patch = api.patch(
        f"/api/v1/tenant/members/{b_membership}", json={"role": "member"}, headers=bearer(a)
    )
    delete = api.delete(f"/api/v1/tenant/members/{b_membership}", headers=bearer(a))
    # Reported as not found, not forbidden: B's rows are invisible, not merely protected.
    assert patch.status_code == 404
    assert delete.status_code == 404
    row = admin_fetch(db, "SELECT role, status FROM memberships WHERE id = $1::uuid", b_membership)
    assert (row[0]["role"], row[0]["status"]) == ("owner", "active")


def test_unknown_and_foreign_ids_are_indistinguishable(api: TestClient, db: PgEnv) -> None:
    a, _ = _two_tenants(api)
    foreign = api.delete(
        f"/api/v1/tenant/members/{_membership_id(db, 'b@example.com')}", headers=bearer(a)
    )
    missing = api.delete(f"/api/v1/tenant/members/{uuid.uuid4()}", headers=bearer(a))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_forged_tenant_claim_is_rejected(api: TestClient, db: PgEnv) -> None:
    """Even a validly signed token is refused if its tenant does not match a membership."""
    a, b = _two_tenants(api)
    claims = jwt.decode(a["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    claims["tid"] = me(api, b)["tenant"]["id"]
    forged = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    response = api.get("/api/v1/tenant/members", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_token_signed_with_another_key_is_rejected(api: TestClient, db: PgEnv) -> None:
    a, _ = _two_tenants(api)
    claims = jwt.decode(a["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    forged = jwt.encode(claims, "x" * 40, algorithm="HS256")
    assert (
        api.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    )


def test_client_supplied_tenant_id_is_not_trusted(api: TestClient, db: PgEnv) -> None:
    a, b = _two_tenants(api)
    b_tenant = me(api, b)["tenant"]["id"]
    # Header and query attempts are ignored; the tenant comes only from the verified membership.
    response = api.get(
        f"/api/v1/tenant?tenant_id={b_tenant}", headers={**bearer(a), "X-Tenant-ID": b_tenant}
    )
    assert response.json()["name"] == "Tenant A"


def test_audit_events_stay_in_their_tenant(api: TestClient, db: PgEnv) -> None:
    a, b = _two_tenants(api)
    a_tenant, b_tenant = me(api, a)["tenant"]["id"], me(api, b)["tenant"]["id"]
    rows = admin_fetch(db, "SELECT DISTINCT tenant_id::text AS t FROM audit_events")
    assert {r["t"] for r in rows} == {a_tenant, b_tenant}


def test_roles_are_enforced(api: TestClient, db: PgEnv) -> None:
    owner = signup(api, "owner@example.com", "Acme")
    tenant_id = me(api, owner)["tenant"]["id"]
    signup(api, "member@example.com", "Member Own")
    member_mid = add_member(db, tenant_id=tenant_id, email="member@example.com", role="member")
    member = api.post(
        "/api/v1/auth/login",
        json={
            "email": "member@example.com",
            "password": "correct horse battery staple",
            "tenant_id": tenant_id,
        },
    ).json()
    owner_mid = _membership_id(db, "owner@example.com")

    # A member cannot manage anyone.
    denied = api.patch(
        f"/api/v1/tenant/members/{owner_mid}", json={"role": "member"}, headers=bearer(member)
    )
    assert denied.status_code == 403

    # The last owner cannot be demoted or removed.
    last = api.patch(
        f"/api/v1/tenant/members/{owner_mid}", json={"role": "admin"}, headers=bearer(owner)
    )
    assert last.status_code == 409
    assert last.json()["error"]["code"] == "last_owner"

    # An owner can promote; the change is audited and effective on the next request.
    promoted = api.patch(
        f"/api/v1/tenant/members/{member_mid}", json={"role": "admin"}, headers=bearer(owner)
    )
    assert promoted.status_code == 204
    assert me(api, member)["role"] == "admin"
    audit = admin_fetch(
        db, "SELECT details FROM audit_events WHERE action = 'membership.role_changed'"
    )
    assert len(audit) == 1

    # An admin still cannot touch an owner.
    blocked = api.delete(f"/api/v1/tenant/members/{owner_mid}", headers=bearer(member))
    assert blocked.status_code == 403
