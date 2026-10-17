"""The reviewed price file: valid, complete for the default models, honest about checking."""

from __future__ import annotations

from pathlib import Path

import pytest

from aurevia.config import DEFAULT_MODELS
from aurevia.platform.prices import (
    REQUIRED_RESOURCES,
    PriceFileError,
    default_price_file,
    main,
    read_price_file,
)


def test_the_reviewed_price_file_covers_every_default_model() -> None:
    entries = read_price_file(default_price_file())
    for provider, model in DEFAULT_MODELS.items():
        priced = {e.resource for e in entries if e.provider == provider and e.model == model}
        assert set(REQUIRED_RESOURCES[provider]) <= priced, (provider, model)


def test_gemini_prices_stay_unverified_until_checked_on_googles_page() -> None:
    # Flip this only after checking https://ai.google.dev/gemini-api/docs/pricing.
    entries = read_price_file(default_price_file())
    gemini = [e for e in entries if e.provider == "gemini"]
    assert gemini and all(not e.verified for e in gemini)
    assert all(e.verified for e in entries if e.provider == "anthropic")


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "prices.toml"
    path.write_text(body, encoding="utf-8")
    return path


ENTRY = """
[[price]]
provider = "gemini"
model = "m"
resource = "{resource}"
currency = "USD"
amount = "{amount}"
per_quantity = 1000000
effective_from = 2026-10-17T00:00:00Z
verified = true
source = "test"
"""


@pytest.mark.parametrize(
    ("resource", "amount", "problem"),
    [
        ("llm_magic_tokens", "1", "llm_magic_tokens"),
        ("llm_input_tokens", "-1", "amount must be"),
        ("llm_input_tokens", "abc", "price entry 1"),
    ],
)
def test_a_bad_entry_is_refused(tmp_path: Path, resource: str, amount: str, problem: str) -> None:
    path = _write(tmp_path, ENTRY.format(resource=resource, amount=amount))
    with pytest.raises(PriceFileError, match=problem):
        read_price_file(path)


def test_duplicate_entries_are_refused(tmp_path: Path) -> None:
    one = ENTRY.format(resource="llm_input_tokens", amount="1")
    with pytest.raises(PriceFileError, match="two entries"):
        read_price_file(_write(tmp_path, one + one))


def test_the_command_needs_the_owner_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    assert main(["load"]) == 1
    assert "AUREVIA_MIGRATION_DATABASE_URL" in capsys.readouterr().err
