"""FastAPI application factory.

Run with: ``uvicorn aurevia.main:create_app --factory``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aurevia import __version__
from aurevia.api.health import router as liveness_router
from aurevia.api.internal import internal_router
from aurevia.api.v1.router import api_v1_router
from aurevia.api.webhooks import router as webhooks_router
from aurevia.campaigns.scheduler import scheduler_loop
from aurevia.config import DEPLOYED_ENVIRONMENTS, Settings, get_settings
from aurevia.db.session import Database
from aurevia.errors import register_exception_handlers
from aurevia.gateway import ModelGateway
from aurevia.logging import configure_logging
from aurevia.memory.jobs import retention_loop
from aurevia.middleware import RequestContextMiddleware
from aurevia.providers.dnd import UnconfiguredDndRegistry
from aurevia.providers.livekit_sip import LiveKitSipTelephony
from aurevia.providers.registry import (
    ClosableModelProvider,
    build_model_provider,
    missing_key_variable,
)
from aurevia.providers.voice_transport import LiveKitTransport
from aurevia.telephony.outbound import outbound_deps

API_V1_PREFIX = "/api/v1"
INTERNAL_PREFIX = "/internal/v1"
RETENTION_INTERVAL_SECONDS = 3600  # transcript purge cadence

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
    retention: asyncio.Task[None] | None = None
    if database is not None:
        await _check_database_role(database, settings)
        if settings.environment != "test":
            retention = asyncio.create_task(retention_loop(database, RETENTION_INTERVAL_SECONDS))
    dialer: asyncio.Task[None] | None = None
    if settings.campaign_scheduler_enabled and settings.environment != "test":
        if app.state.telephony is None:
            logger.warning("Campaign auto-dialer enabled but phone calls are not configured")
        else:
            logger.warning("Campaign auto-dialer is running (gate and plan limits apply)")
            dialer = asyncio.create_task(
                scheduler_loop(
                    outbound_deps(app.state), settings.campaign_scheduler_interval_seconds
                )
            )
    try:
        yield
    finally:
        if retention is not None:
            retention.cancel()
        if dialer is not None:
            dialer.cancel()
        provider: ClosableModelProvider | None = app.state.model_provider
        if provider is not None:
            await provider.aclose()
        if database is not None:
            await database.dispose()
        logger.info("Aurevia stopped")


def _build_model_gateway(
    settings: Settings,
) -> tuple[ClosableModelProvider, ModelGateway] | None:
    provider = build_model_provider(settings)
    if provider is None:
        logger.warning(
            "AI model not configured: model endpoints will return 503",
            extra={
                "fields": {
                    "ai_provider": settings.ai_provider,
                    "missing": missing_key_variable(settings),
                }
            },
        )
        return None
    gateway = ModelGateway(
        provider,
        model=settings.resolved_llm_model,
        max_tokens=settings.llm_max_tokens,
        first_token_timeout_seconds=settings.llm_first_token_timeout_seconds,
        total_timeout_seconds=settings.llm_total_timeout_seconds,
        fallback_models=settings.llm_fallback_models,
    )
    logger.info(
        "AI model configured",
        extra={
            "fields": {
                "ai_provider": settings.ai_provider,
                "model": settings.resolved_llm_model,
                "fallback_policy": settings.resolved_fallback_policy,
                "fallback_models": ",".join(settings.llm_fallback_models) or "none",
            }
        },
    )
    return provider, gateway


def _build_voice_transport(settings: Settings) -> LiveKitTransport | None:
    if not settings.voice_configured:
        return None
    assert settings.livekit_url and settings.livekit_public_url  # noqa: S101 - voice_configured
    assert settings.livekit_api_key and settings.livekit_api_secret  # noqa: S101
    return LiveKitTransport(
        url=settings.livekit_url,
        public_url=settings.livekit_public_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
    )


def _build_telephony(settings: Settings) -> LiveKitSipTelephony | None:
    if settings.telephony_provider != "livekit_sip" or not settings.voice_configured:
        return None
    if not settings.livekit_sip_outbound_trunk_id:
        logger.warning("Phone calls disabled: set AUREVIA_LIVEKIT_SIP_OUTBOUND_TRUNK_ID")
        return None
    assert settings.livekit_url and settings.livekit_api_key  # noqa: S101 - voice_configured
    assert settings.livekit_api_secret  # noqa: S101
    if settings.telephony_mode == "live":
        logger.warning("Telephony is in live mode; the gate still blocks unreviewed policy packs")
    return LiveKitSipTelephony(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret.get_secret_value(),
        outbound_trunk_id=settings.livekit_sip_outbound_trunk_id,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        settings.log_level,
        json_output=settings.log_json,
        redact_values=settings.secret_values(),
    )

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

    # Optional integrations: unset configuration leaves them off (their endpoints return 503),
    # and tests swap in fakes through the same attributes.
    model = _build_model_gateway(settings)
    app.state.model_provider, app.state.model_gateway = model if model else (None, None)
    app.state.voice_transport = _build_voice_transport(settings)
    app.state.telephony = _build_telephony(settings)
    # No national DND registry is integrated yet: every lookup answers "unknown", which the
    # policy pack treats as a block for anyone but the tenant's own test numbers.
    app.state.dnd_registry = UnconfiguredDndRegistry()
    # The time compliance decisions are taken at; tests pin it (calling windows).
    app.state.clock = lambda: datetime.now(UTC)

    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    register_exception_handlers(app)
    app.include_router(liveness_router)
    app.include_router(api_v1_router, prefix=API_V1_PREFIX)
    app.include_router(internal_router, prefix=INTERNAL_PREFIX)
    app.include_router(webhooks_router)
    return app
