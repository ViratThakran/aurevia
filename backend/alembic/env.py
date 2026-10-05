"""Alembic environment: async engine, URL and app role taken from Aurevia settings.

Programmatic callers (tests) may pass ``database_url`` and ``app_role`` through
``Config.attributes`` instead.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from aurevia.config import Settings
from aurevia.db.base import Base
from aurevia.identity import models as _identity_models  # noqa: F401 - registers tables
from aurevia.usage import models as _usage_models  # noqa: F401
from aurevia.voice import models as _voice_models  # noqa: F401

config = context.config
# CLI runs log progress; programmatic callers (tests) keep their own logging setup.
if config.config_file_name is not None and "database_url" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _resolve() -> tuple[str, str]:
    url = config.attributes.get("database_url")
    role = config.attributes.get("app_role")
    if url is None or role is None:
        settings = Settings()
        secret = settings.migration_database_url or settings.database_url
        if secret is None:
            raise RuntimeError("Set AUREVIA_MIGRATION_DATABASE_URL to run migrations")
        url = url or secret.get_secret_value()
        role = role or settings.database_app_role
    config.attributes["app_role"] = role
    return url, role


def run_migrations_offline() -> None:
    url, _ = _resolve()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, _ = _resolve()
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
