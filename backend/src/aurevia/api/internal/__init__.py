"""Service-to-service endpoints (voice worker). Never called by browsers."""

from fastapi import APIRouter

from aurevia.api.internal import calls

internal_router = APIRouter()
internal_router.include_router(calls.router)
