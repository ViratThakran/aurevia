"""Phase 9: rate limits slow password guessing and floods."""

from __future__ import annotations

from fastapi.testclient import TestClient

from aurevia.main import create_app
from aurevia.ratelimit import MAX_KEYS, SlidingWindowLimiter, client_ip
from tests.conftest import SettingsFactory


def test_sliding_window() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=10)
    assert limiter.hit("a", now=0) is None
    assert limiter.hit("a", now=1) is None
    assert limiter.hit("a", now=2) == 8  # wait until the first hit leaves the window
    assert limiter.hit("b", now=2) is None  # keys are independent
    assert limiter.hit("a", now=10.5) is None


def test_memory_is_bounded() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    for i in range(MAX_KEYS + 10):
        limiter.hit(f"k{i}", now=0)
    assert len(limiter._hits) == MAX_KEYS


def test_forwarded_for_is_trusted_only_when_configured() -> None:
    scope = {"client": ("10.0.0.1", 1), "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")]}
    assert client_ip(scope, trust_forwarded=False) == "10.0.0.1"
    assert client_ip(scope, trust_forwarded=True) == "203.0.113.9"


def test_api_requests_are_limited_per_ip(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(rate_limit_api_per_ip_per_minute=3))
    with TestClient(app) as client:
        codes = [client.get("/api/v1/health/ready").status_code for _ in range(4)]
        assert codes[3] == 429
        last = client.get("/api/v1/health/ready")
        assert last.json()["error"]["code"] == "rate_limited"
        assert int(last.headers["Retry-After"]) >= 1
        assert client.get("/health").status_code == 200  # probes are never limited


def test_sign_in_attempts_are_limited_per_email(make_settings: SettingsFactory) -> None:
    app = create_app(make_settings(rate_limit_login_per_email_per_15_minutes=2))
    with TestClient(app, raise_server_exceptions=False) as client:
        body = {"email": "Victim@Example.com", "password": "guess"}
        codes = [client.post("/api/v1/auth/login", json=body).status_code for _ in range(3)]
        # The first two reach the credential check (503 here: no database); the third is cut off.
        assert codes[2] == 429 and 429 not in codes[:2]
        other = client.post("/api/v1/auth/login", json={**body, "email": "someone@example.com"})
        assert other.status_code != 429
