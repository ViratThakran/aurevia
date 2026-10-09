"""Platform operator command for policy versions. Not an API: tenants cannot certify compliance.

Runs with the schema owner's connection (``AUREVIA_MIGRATION_DATABASE_URL``)::

    python -m aurevia.compliance.operator list
    python -m aurevia.compliance.operator publish path/to/pack-version.json
    python -m aurevia.compliance.operator review india-2026-10-draft-1 \\
        --by "Name, Firm" --reference "Opinion ref / date"
    python -m aurevia.compliance.operator retire india-2026-10-draft-1

``review`` is the step that eventually allows live calls under a version. Record it only after
counsel has reviewed exactly that version's rules (``list`` shows them with their hash).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aurevia.compliance.models import PolicyVersion
from aurevia.compliance.policy import PolicyRules, PolicyStatus
from aurevia.config import Settings


class OperatorError(Exception):
    pass


async def publish(session: AsyncSession, raw: str) -> PolicyVersion:
    """Add a new draft version from a pack-version JSON document."""
    data = json.loads(raw)
    rules = PolicyRules.model_validate(data["rules"])  # rejects malformed rules
    existing = await session.scalar(
        select(PolicyVersion).where(PolicyVersion.version == data["version"])
    )
    if existing is not None:
        raise OperatorError(f"version {data['version']} already exists; versions never change")
    version = PolicyVersion(
        pack=data["pack"],
        version=data["version"],
        rules=rules.model_dump(mode="json"),
        source_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        notes=data.get("notes"),
        status=PolicyStatus.DRAFT,
    )
    session.add(version)
    await session.commit()
    return version


async def _get(session: AsyncSession, version: str) -> PolicyVersion:
    row = await session.scalar(select(PolicyVersion).where(PolicyVersion.version == version))
    if row is None:
        raise OperatorError(f"no policy version {version}")
    return row


async def review(
    session: AsyncSession, version: str, *, by: str, reference: str, now: datetime | None = None
) -> PolicyVersion:
    if not by.strip() or not reference.strip():
        raise OperatorError("a review needs the reviewer and a reference to their opinion")
    row = await _get(session, version)
    if row.status != PolicyStatus.DRAFT:
        raise OperatorError(f"only a draft can be marked reviewed (this one is {row.status})")
    row.status = PolicyStatus.REVIEWED
    row.reviewed_at = now or datetime.now(UTC)
    row.reviewed_by = by.strip()
    row.review_reference = reference.strip()
    await session.commit()
    return row


async def retire(session: AsyncSession, version: str, now: datetime | None = None) -> PolicyVersion:
    row = await _get(session, version)
    if row.status == PolicyStatus.RETIRED:
        return row
    row.status = PolicyStatus.RETIRED
    row.retired_at = now or datetime.now(UTC)
    await session.commit()
    return row


async def list_versions(session: AsyncSession) -> list[PolicyVersion]:
    return list(await session.scalars(select(PolicyVersion).order_by(PolicyVersion.created_at)))


def _describe(v: PolicyVersion) -> str:
    review = f" reviewed by {v.reviewed_by} ({v.review_reference})" if v.reviewed_by else ""
    return f"{v.version:<32} {v.pack:<8} {v.status:<9} sha256={v.source_sha256[:12]}{review}"


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.migration_database_url is None:
        raise OperatorError("set AUREVIA_MIGRATION_DATABASE_URL (the schema owner's connection)")
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "list":
                for v in await list_versions(session):
                    print(_describe(v))
            elif args.command == "publish":
                print("published:", _describe(await publish(session, args.raw)))
            elif args.command == "review":
                v = await review(session, args.version, by=args.by, reference=args.reference)
                print("reviewed:", _describe(v))
            elif args.command == "retire":
                print("retired:", _describe(await retire(session, args.version)))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.compliance.operator")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    publish_cmd = commands.add_parser("publish")
    publish_cmd.add_argument("file")
    review_cmd = commands.add_parser("review")
    review_cmd.add_argument("version")
    review_cmd.add_argument("--by", required=True)
    review_cmd.add_argument("--reference", required=True)
    retire_cmd = commands.add_parser("retire")
    retire_cmd.add_argument("version")
    args = parser.parse_args(argv)
    if args.command == "publish":
        args.raw = Path(args.file).read_text("utf-8")
    try:
        asyncio.run(_run(args))
    except OperatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
