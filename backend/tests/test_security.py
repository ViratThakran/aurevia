from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from aurevia.errors import AuthenticationError
from aurevia.identity.security import (
    AccessClaims,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from tests.conftest import TEST_JWT_SECRET

CLAIMS = AccessClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), membership_id=uuid.uuid4())


def test_password_hash_round_trip() -> None:
    hashed = hash_password("a long enough passphrase")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a long enough passphrase")
    assert not verify_password(hashed, "a long enough passphrasE")


def test_verify_password_handles_missing_and_corrupt_hashes() -> None:
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


def test_access_token_round_trip() -> None:
    token = create_access_token(CLAIMS, secret=TEST_JWT_SECRET, ttl_seconds=300)
    assert decode_access_token(token, secret=TEST_JWT_SECRET) == CLAIMS


def test_expired_access_token_is_rejected() -> None:
    issued = datetime.now(UTC) - timedelta(minutes=10)
    token = create_access_token(CLAIMS, secret=TEST_JWT_SECRET, ttl_seconds=300, now=issued)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=TEST_JWT_SECRET)


def test_wrong_secret_is_rejected() -> None:
    token = create_access_token(CLAIMS, secret=TEST_JWT_SECRET, ttl_seconds=300)
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret="w" * 40)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(typ="refresh"),
        lambda c: c.pop("tid"),
        lambda c: c.update(sub="not-a-uuid"),
    ],
)
def test_malformed_claims_are_rejected(mutate: object) -> None:
    token = create_access_token(CLAIMS, secret=TEST_JWT_SECRET, ttl_seconds=300)
    claims = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    mutate(claims)  # type: ignore[operator]
    forged = jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_access_token(forged, secret=TEST_JWT_SECRET)


def test_alg_none_is_rejected() -> None:
    token = create_access_token(CLAIMS, secret=TEST_JWT_SECRET, ttl_seconds=300)
    claims = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    with pytest.raises(AuthenticationError):
        decode_access_token(unsigned, secret=TEST_JWT_SECRET)


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    token, digest = new_refresh_token()
    other, _ = new_refresh_token()
    assert token != other
    assert digest == hash_refresh_token(token)
    assert token not in digest and len(digest) == 64
