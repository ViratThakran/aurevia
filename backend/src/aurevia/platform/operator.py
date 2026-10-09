"""Platform operator command: who is an Aurevia platform administrator. Not an API.

Runs with the schema owner's connection (``AUREVIA_MIGRATION_DATABASE_URL``)::

    python -m aurevia.platform.operator list-admins
    python -m aurevia.platform.operator grant-admin someone@aurevia.example
    python -m aurevia.platform.operator revoke-admin someone@aurevia.example
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aurevia.config import Settings
from aurevia.identity.models import User
from aurevia.identity.service import normalize_email


class OperatorError(Exception):
    pass


async def set_admin(session: AsyncSession, email: str, *, admin: bool) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        raise OperatorError("no user with that email (they must sign up first)")
    user.is_platform_admin = admin
    await session.commit()
    return user


async def list_admins(session: AsyncSession) -> list[str]:
    return list(
        await session.scalars(
            select(User.email).where(User.is_platform_admin.is_(True)).order_by(User.email)
        )
    )


async def _run(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.migration_database_url is None:
        raise OperatorError("set AUREVIA_MIGRATION_DATABASE_URL (the schema owner's connection)")
    engine = create_async_engine(settings.migration_database_url.get_secret_value())
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            if args.command == "list-admins":
                for email in await list_admins(session):
                    print(email)
            else:
                user = await set_admin(session, args.email, admin=args.command == "grant-admin")
                print(f"{user.email}: platform admin = {user.is_platform_admin}")
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurevia.platform.operator")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-admins")
    for name in ("grant-admin", "revoke-admin"):
        commands.add_parser(name).add_argument("email")
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args))
    except OperatorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
