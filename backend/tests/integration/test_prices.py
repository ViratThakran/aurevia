"""Loading the price file (adds rows only) and the startup check for missing model prices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aurevia.platform.models import PriceResource
from aurevia.platform.prices import (
    default_price_file,
    load_prices,
    missing_prices,
    read_price_file,
    warn_missing_prices,
)
from tests.conftest import SettingsFactory
from tests.integration.conftest import PgEnv, admin_execute, admin_fetch

LATER = datetime(2026, 10, 18, tzinfo=UTC)


def _session[T](url: str, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await action(session)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _rows(db: PgEnv) -> list[Any]:
    return admin_fetch(
        db, "SELECT provider, model, resource, amount, effective_from FROM prices ORDER BY 1, 2, 3"
    )


def test_loading_adds_only_new_verified_rows(db: PgEnv) -> None:
    entries = read_price_file(default_price_file())
    verified = [e for e in entries if e.verified]
    first = _session(db.owner_url, lambda s: load_prices(s, entries))
    assert len(first.added) == len(verified)
    assert len(first.skipped_unverified) == len(entries) - len(verified)
    assert {r["provider"] for r in _rows(db)} == {"anthropic"}  # Gemini is unverified

    again = _session(db.owner_url, lambda s: load_prices(s, entries))
    assert again.added == [] and len(again.already_present) == len(verified)
    assert len(_rows(db)) == len(verified)  # running it twice changes nothing

    # A price change is a new entry with a later date: a new row, the old one kept.
    changed = replace(verified[0], amount=verified[0].amount + Decimal(1), effective_from=LATER)
    third = _session(db.owner_url, lambda s: load_prices(s, [changed]))
    assert third.added == [changed] and len(_rows(db)) == len(verified) + 1


def test_unverified_prices_load_only_when_asked(db: PgEnv) -> None:
    entries = read_price_file(default_price_file())
    result = _session(db.owner_url, lambda s: load_prices(s, entries, include_unverified=True))
    assert result.skipped_unverified == [] and len(result.added) == len(entries)
    assert {r["provider"] for r in _rows(db)} == {"anthropic", "gemini"}


def test_startup_check_names_each_missing_price(
    db: PgEnv, make_settings: SettingsFactory, caplog: pytest.LogCaptureFixture
) -> None:
    settings = make_settings(ai_provider="anthropic", llm_model="claude-opus-5-5")
    caplog.set_level(logging.WARNING, logger="aurevia.platform.prices")
    # The app role can read prices, so the running app can do this check.
    warnings = _session(db.app_url, lambda s: warn_missing_prices(s, settings))
    assert len(warnings) == 4 and len(caplog.records) == 4
    assert {r.__dict__["fields"]["resource"] for r in caplog.records} == {
        r.value for r in PriceResource if r.value.startswith("llm_")
    }

    entries = read_price_file(default_price_file())
    _session(db.owner_url, lambda s: load_prices(s, entries))
    now = datetime.now(UTC)
    assert (
        _session(db.app_url, lambda s: missing_prices(s, "anthropic", ["claude-opus-5-5"], now=now))
        == []
    )
    # A price that only takes effect later does not count yet.
    early = now - timedelta(days=365)
    missing = _session(
        db.app_url, lambda s: missing_prices(s, "anthropic", ["claude-opus-5-5"], now=early)
    )
    assert len(missing) == 4


def test_a_star_price_covers_any_model_of_the_provider(db: PgEnv) -> None:
    for resource in ("llm_input_tokens", "llm_cached_input_tokens", "llm_output_tokens"):
        admin_execute(
            db,
            "INSERT INTO prices (id, provider, resource, model, currency, amount, per_quantity, "
            f"effective_from) VALUES (gen_random_uuid(), 'gemini', '{resource}', '*', 'USD', 1, "
            "1000000, now() - interval '1 day')",
        )
    now = datetime.now(UTC)
    assert _session(db.app_url, lambda s: missing_prices(s, "gemini", ["any"], now=now)) == []


def test_the_command_runs_on_its_own_as_deploy_sh_runs_it(db: PgEnv, tmp_path: Any) -> None:
    """A fresh process (no test imports) must load the price file: deploy.sh depends on it."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("AUREVIA_")}
    env["AUREVIA_MIGRATION_DATABASE_URL"] = db.owner_url
    for command in (["load"], ["check"]):
        done = subprocess.run(  # noqa: S603 - fixed arguments, test only
            [sys.executable, "-m", "aurevia.platform.prices", *command],
            cwd=tmp_path,  # no .env here
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert "Traceback" not in done.stderr, done.stderr
        if command == ["load"]:
            assert done.returncode == 0 and "added" in done.stdout, done.stdout
    assert {r["provider"] for r in _rows(db)} == {"anthropic"}
