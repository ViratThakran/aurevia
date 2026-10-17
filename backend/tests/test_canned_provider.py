"""The canned model provider: benchmarks of the speech path only, never in a deployment."""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import ValidationError

from aurevia.providers.fakes import CANNED_REPLIES, CannedModelProvider
from aurevia.providers.model import ModelMessage, ModelRequest
from aurevia.providers.registry import build_model_provider
from tests.conftest import SettingsFactory


def _request(system: str = "You are a sales agent.") -> ModelRequest:
    return ModelRequest(
        model="canned-v1",
        system=system,
        messages=(ModelMessage(role="user", content="Hi"),),
        max_tokens=100,
    )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_canned_is_refused_in_deployed_environments(
    make_settings: SettingsFactory, environment: str
) -> None:
    with pytest.raises(ValidationError, match="benchmarks only"):
        make_settings(
            environment=environment,
            ai_provider="canned",
            database_url="postgresql+asyncpg://u:p@h/db",
            jwt_secret="x" * 64,
        )


def test_canned_needs_no_key_and_is_built_by_the_registry(make_settings: SettingsFactory) -> None:
    provider = build_model_provider(make_settings(ai_provider="canned", canned_first_token_ms=7))
    assert isinstance(provider, CannedModelProvider) and provider.first_token_ms == 7


def test_canned_streams_a_fixed_reply_after_the_first_token_delay() -> None:
    async def run() -> tuple[str, float]:
        provider = CannedModelProvider(first_token_ms=50)
        started, first, text = time.monotonic(), None, ""
        async for event in provider.stream(_request()):
            if event.delta and first is None:
                first = time.monotonic() - started
            text += event.delta
        assert first is not None
        return text, first

    text, first = asyncio.run(run())
    assert text == CANNED_REPLIES[0] and first >= 0.045


def test_canned_bookkeeping_pass_is_empty_and_immediate() -> None:
    async def run() -> list[str]:
        provider = CannedModelProvider(first_token_ms=5000)
        return [e.delta async for e in provider.stream(_request("# Bookkeeping pass")) if e.delta]

    assert asyncio.run(asyncio.wait_for(run(), timeout=1)) == []
