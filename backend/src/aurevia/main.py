"""FastAPI application factory.

Run with: ``uvicorn aurevia.main:create_app --factory``
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aurevia import __version__
from aurevia.api.health import router as liveness_router
from aurevia.api.v1.router import api_v1_router
from aurevia.config import DEPLOYED_ENVIRONMENTS, Settings, get_settings
from aurevia.db.session import Database
from aurevia.errors import register_exception_handlers
from aurevia.logging import configure_logging
from aurevia.middleware import RequestContextMiddleware

API_V1_PREFIX = "/api/v1"

logger = logging.getLogger(__name__)


class UnsafeDatabaseRoleError(RuntimeError):
    """The app is connected as a role that would bypass row-level security."""


async def _check_database_role(database: Database, settings: Settings) -> None:
    """Refuse to run in staging/production as a role that skips tenant isolation."""
    try:
        check = await database.check_role()
    except Exception:
        # Unreachable database: readiness reports it; startup does not crash on it.
        logger.warning("Database role check skipped: database unreachable", exc_info=True)
        return
    if not check.bypasses_rls:
        return
    message = "Database role bypasses row-level security; use the application role"
    if settings.environment in DEPLOYED_ENVIRONMENTS:
        raise UnsafeDatabaseRoleError(message)
    logger.warning(message, extra={"fields": {"role": check.role}})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    database: Database | None = app.state.database
    logger.info(
        "Aurevia starting",
        extra={"fields": {"environment": settings.environment, "version": __version__}},
    )
    if database is not None:
        await _check_database_role(database, settings)
    try:
        yield
    finally:
        if database is not None:
            await database.dispose()
        logger.info("Aurevia stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="Aurevia API",
        version=__version__,
        debug=settings.debug,
        lifespan=lifespan,
        # Interactive docs and the schema are not exposed in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.readiness_checks = {}
    app.state.database = None
    if settings.database_url is not None:
        database = Database(settings.database_url.get_secret_value())
        app.state.database = database
        app.state.readiness_checks["database"] = database.ping

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(liveness_router)
    app.include_router(api_v1_router, prefix=API_V1_PREFIX)
    return app
