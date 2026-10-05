"""Structured error handling.

Every error response uses one envelope::

    {"error": {"code": str, "message": str, "request_id": str, "details": list | dict | null}}

Unhandled exceptions return a generic 500: internals are logged server-side, never returned.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
}


class AureviaError(Exception):
    """Base class for expected, client-safe application errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Any = None,
        status_code: int | None = None,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or HTTPStatus(status_code or self.status_code).phrase
        self.details = details
        self.headers = headers
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        super().__init__(self.message)


class AuthenticationError(AureviaError):
    """Missing, invalid or expired credentials. Messages stay generic on purpose."""

    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Authentication required", **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class PermissionDeniedError(AureviaError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AureviaError):
    status_code = 404
    code = "not_found"


class ConflictError(AureviaError):
    status_code = 409
    code = "conflict"


class ServiceUnavailableError(AureviaError):
    status_code = 503
    code = "service_unavailable"


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = {"X-Request-ID": request_id, **(headers or {})}
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": request_id,
                "details": details,
            }
        },
        headers=response_headers,
    )


async def _handle_aurevia_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AureviaError)  # noqa: S101 - narrows type for the handler
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    status_code = exc.status_code
    return error_response(
        request,
        status_code=status_code,
        code=_HTTP_CODES.get(status_code, f"http_{status_code}"),
        # Standard phrase only: framework `detail` strings are not part of our contract.
        message=HTTPStatus(status_code).phrase,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    # Deliberately omit the offending `input`: it may contain passwords or tokens.
    details = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details=details,
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception",
        exc_info=exc,
        extra={
            "request_id": _request_id(request),
            "fields": {"method": request.method, "path": request.url.path},
        },
    )
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Internal Server Error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AureviaError, _handle_aurevia_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
