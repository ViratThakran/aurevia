"""The reviewed price file, its loader, and the startup check for missing model prices.

Prices are data, never code: they live in ``prices.toml`` (reviewed in pull requests) and in
the append-only ``prices`` table. Loading only ever adds rows; an entry that is already in the
database is skipped, so running it again changes nothing.

Runs with the schema owner's connection (``AUREVIA_MIGRATION_DATABASE_URL``), after
migrations::

    python -m aurevia.platform.prices load [--file PATH] [--include-unverified]
    python -m aurevia.platform.prices check
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aurevia.config import Settings
from aurevia.platform.models import Price, PriceResource

logger = logging.getLogger(__name__)

# Model prices each provider needs for its usage to be fully priced.
REQUIRED_RESOURCES: dict[str, tuple[PriceResource, ...]] = {
    "gemini": (
        PriceResource.LLM_INPUT_TOKENS,
        PriceResource.LLM_CACHED_INPUT_TOKENS,
        PriceResource.LLM_OUTPUT_TOKENS,
    ),
    "anthropic": (
        PriceResource.LLM_INPUT_TOKENS,
        PriceResource.LLM_CACHED_INPUT_TOKENS,
        PriceResource.LLM_CACHE_WRITE_INPUT_TOKENS,
        PriceResource.LLM_OUTPUT_TOKENS,
    ),
}


class PriceFileError(Exception):
    pass


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str
    resource: PriceResource
    currency: str
    amount: Decimal
    per_quantity: int
    effective_from: datetime
    verified: bool
    source: str


@dataclass
class LoadResult:
    added: list[PriceEntry] = field(default_factory=list)
    already_present: list[PriceEntry] = field(default_factory=list)
    skipped_unverified: list[PriceEntry] = field(default_factory=list)


def default_price_file() -> Path:
    return Path(str(resources.files("aurevia.platform").joinpath("prices.toml")))


def _entry(raw: dict[str, Any], index: int) -> PriceEntry:
    where = f"price entry {index + 1}"
    try:
        resource = PriceResource(raw["resource"])
        amount = Decimal(str(raw["amount"]))
        per_quantity = int(raw["per_quantity"])
        effective_from = raw["effective_from"]
        provider, model, currency = str(raw["provider"]), str(raw["model"]), str(raw["currency"])
        verified, source = raw["verified"], str(raw["source"])
    except KeyError as exc:
        raise PriceFileError(f"{where}: missing {exc.args[0]}") from None
    except (ValueError, InvalidOperation) as exc:
        raise PriceFileError(f"{where}: {exc}") from None
    if not isinstance(verified, bool):
        raise PriceFileError(f"{where}: verified must be true or false")
    if not isinstance(effective_from, datetime) or effective_from.tzinfo is None:
        raise PriceFileError(f"{where}: effective_from must be a date-time with a time zone")
    if amount < 0 or per_quantity <= 0:
        raise PriceFileError(f"{where}: amount must be >= 0 and per_quantity > 0")
    if len(currency) != 3 or not currency.isupper():
        raise PriceFileError(f"{where}: currency must be a 3-letter code")
    if not provider or not model or not source:
        raise PriceFileError(f"{where}: provider, model and source must not be empty")
    return PriceEntry(
        provider, model, resource, currency, amount, per_quantity, effective_from, verified, source
    )


def read_price_file(path: Path) -> list[PriceEntry]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PriceFileError(f"cannot read {path}: {exc}") from None
    entries = [_entry(raw, i) for i, raw in enumerate(data.get("price", []))]
    keys = [(e.provider, e.model, e.resource, e.currency, e.effective_from) for e in entries]
    if len(set(keys)) != len(keys):
        raise PriceFileError("two entries share provider, model, resource, currency and date")
    return entries


async def _exists(session: AsyncSession, entry: PriceEntry) -> bool:
    found = await session.scalar(
        select(Price.id).where(
            Price.provider == entry.provider,
            Price.model == entry.model,
            Price.resource == entry.resource,
            Price.currency == entry.currency,
            Price.amount == entry.amount,
            Price.per_quantity == entry.per_quantity,
            Price.effective_from == entry.effective_from,
        )
    )
    return found is not None


async def load_prices(
    session: AsyncSession, entries: Iterable[PriceEntry], *, include_unverified: bool = False
) -> LoadResult:
    """Insert the entries not already in ``prices``. Never updates or deletes a row."""
    result = LoadResult()
    for entry in entries:
        if not entry.verified and not include_unverified:
            result.skipped_unverified.append(entry)
        elif await _exists(session, entry):
            result.already_present.append(entry)
        else:
            session.add(
                Price(
                    provider=entry.provider,
                    model=entry.model,
                    resource=entry.resource,
                    currency=entry.currency,
                    amount=entry.amount,
                    per_quantity=entry.per_quantity,
                    effective_from=entry.effective_from,
                )
            )
            result.added.append(entry)
    await session.commit()
    return result


async def missing_prices(
    session: AsyncSession, provider: str, models: Sequence[str], *, now: datetime
) -> list[tuple[str, PriceResource]]:
    """(model, resource) pairs with no price in effect now, for the given provider's models."""
    missing = []
    for model in dict.fromkeys(models):
        for resource in REQUIRED_RESOURCES.get(provider, ()):
            found = await session.scalar(
                select(Price.id)
                .where(
                    Price.provider == provider,
                    Price.resource == resource,
                    or_(Price.model == model, Price.model == "*"),
                    Price.effective_from <= now,
                )
                .limit(1)
            )
            if found is None:
                missing.append((model, resource))
    return missing


def configured_models(settings: Settings) -> list[str]:
    return [settings.resolved_llm_model, *settings.llm_fallback_models]


async def warn_missing_prices(session: AsyncSession, settings: Settings) -> list[str]:
    """Log one warning per missing model price; returns the warnings (empty: all priced)."""
    provider = settings.ai_provider
    missing = await missing_prices(
        session, provider, configured_models(settings), now=datetime.now(UTC)
    )
    warnings = []
    for model, resource in missing:
        message = f"No {resource.value} price for {provider} model {model}"
        warnings.append(message)
        logger.warning(
            "Model price missing: its usage is reported as unpriced and counts as zero "
            "toward spend limits",
            extra={"fields": {"provider": provider, "model": model, "resource": resource.value}},
        )
    return warnings


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    if settings.migration_database_url is None:
        raise PriceFileError("set AUREVIA_MIGRATION_DATABASE_URL (the schema owner's connection)")
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "load":
                entries = read_price_file(Path(args.file) if args.file else default_price_file())
                result = await load_prices(
                    session, entries, include_unverified=args.include_unverified
                )
                print(
                    f"prices: {len(result.added)} added, {len(result.already_present)} already "
                    f"present, {len(result.skipped_unverified)} unverified skipped"
                )
                for entry in result.skipped_unverified:
                    print(
                        f"  unverified, not loaded: {entry.provider} {entry.model} "
                        f"{entry.resource.value}"
                    )
                return 0
            warnings = await warn_missing_prices(session, settings)
            for message in warnings:
                print(message)
            return 1 if warnings else 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.platform.prices")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load", help="add the price file's entries not yet in the database")
    load.add_argument("--file", help="price file (default: the reviewed prices.toml)")
    load.add_argument(
        "--include-unverified", action="store_true", help="also load entries marked unverified"
    )
    commands.add_parser("check", help="list model prices missing for the configured models")
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except PriceFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
