from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aurevia.config import Settings
from aurevia.main import create_app

SettingsFactory = Callable[..., Settings]

# Obviously fake, test-only values. Not real credentials.
TEST_JWT_SECRET = "t" * 40
TEST_DATABASE_URL = "postgresql+asyncpg://test_user:test_pw@localhost:5432/test_db"


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must never pick up AUREVIA_* variables from the developer's shell."""
    import os

    for key in list(os.environ):
        if key.startswith("AUREVIA_"):
            monkeypatch.delenv(key)


@pytest.fixture
def make_settings() -> SettingsFactory:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {"environment": "test", "log_json": True}
        values.update(overrides)
        # _env_file=None: never read a developer's local .env during tests.
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def app(make_settings: SettingsFactory) -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Context manager runs the lifespan (startup/shutdown).
    # raise_server_exceptions=False: assert on the 500 response like a real client would.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
