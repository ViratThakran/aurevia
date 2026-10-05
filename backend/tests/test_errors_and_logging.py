from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from aurevia.errors import AureviaError
from aurevia.logging import JsonFormatter, configure_logging


class _Payload(BaseModel):
    password: str
    age: int


@pytest.fixture
def error_app(app: FastAPI) -> FastAPI:
    """The shared app plus routes that deliberately raise, registered for tests only."""

    async def boom() -> None:
        raise RuntimeError("secret internal detail: db password is hunter2")

    async def domain_error() -> None:
        raise AureviaError("Lead is locked", code="lead_locked", status_code=409, details={"x": 1})

    async def echo(payload: _Payload) -> dict[str, int]:
        return {"age": payload.age}

    app.add_api_route("/_test/boom", boom)
    app.add_api_route("/_test/domain-error", domain_error)
    app.add_api_route("/_test/echo", echo, methods=["POST"])
    return app


@pytest.fixture
def error_client(error_app: FastAPI) -> TestClient:
    return TestClient(error_app, raise_server_exceptions=False)


def _assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "request_id", "details"}
    assert error["code"] == code
    return error


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    error = _assert_envelope(response.json(), "not_found")
    assert error["message"] == "Not Found"


def test_method_not_allowed_uses_error_envelope(client: TestClient) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    _assert_envelope(response.json(), "method_not_allowed")


def test_validation_error_envelope_never_echoes_input(error_client: TestClient) -> None:
    response = error_client.post(
        "/_test/echo", json={"password": "hunter2-super-secret", "age": "not-an-int"}
    )
    assert response.status_code == 422
    error = _assert_envelope(response.json(), "validation_error")
    assert isinstance(error["details"], list)
    assert error["details"][0]["loc"] == ["body", "age"]
    assert "hunter2-super-secret" not in response.text
    assert "not-an-int" not in response.text


def test_domain_error_is_serialised_with_its_status_and_code(error_client: TestClient) -> None:
    response = error_client.get("/_test/domain-error")
    assert response.status_code == 409
    error = _assert_envelope(response.json(), "lead_locked")
    assert error["message"] == "Lead is locked"
    assert error["details"] == {"x": 1}


def test_unhandled_exception_returns_generic_500(
    error_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = error_client.get("/_test/boom")
    assert response.status_code == 500
    error = _assert_envelope(response.json(), "internal_error")
    assert error["message"] == "Internal Server Error"
    assert "hunter2" not in response.text
    # ...but the detail is available server-side for debugging.
    assert any(r.exc_info is not None and "hunter2" in str(r.exc_info[1]) for r in caplog.records)
    assert response.headers["x-request-id"] == error["request_id"]


def test_response_carries_generated_request_id(client: TestClient) -> None:
    response = client.get("/health")
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32


def test_valid_incoming_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/nope", headers={"X-Request-ID": "trace-abc-12345"})
    assert response.headers["x-request-id"] == "trace-abc-12345"
    assert response.json()["error"]["request_id"] == "trace-abc-12345"


@pytest.mark.parametrize(
    "bad_id", ["short", "x" * 65, "has space in it", "bad<script>id", "new\\nline-id-xxxxxx"]
)
def test_unsafe_incoming_request_id_is_replaced(client: TestClient, bad_id: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": bad_id})
    assert response.headers["x-request-id"] != bad_id
    assert len(response.headers["x-request-id"]) == 32


def test_access_log_has_request_id_and_no_query_string(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="aurevia.access"):
        response = client.get(
            "/nope?token=supersecret", headers={"X-Request-ID": "trace-log-12345"}
        )
    record = next(r for r in caplog.records if r.name == "aurevia.access")
    fields = record.fields  # type: ignore[attr-defined]
    assert fields["path"] == "/nope"
    assert fields["status"] == 404
    assert "supersecret" not in json.dumps(fields)
    assert response.headers["x-request-id"] == "trace-log-12345"


def test_healthchecks_are_not_logged_at_info(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="aurevia.access"):
        client.get("/health")
    assert not [r for r in caplog.records if r.name == "aurevia.access"]


def test_json_formatter_output_shape() -> None:
    record = logging.LogRecord(
        "aurevia.test", logging.WARNING, __file__, 1, "hello %s", ("w",), None
    )
    record.request_id = "rid-12345678"
    record.fields = {"tenant": "t1", "message": "must-not-override"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello w"
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "aurevia.test"
    assert payload["request_id"] == "rid-12345678"
    assert payload["tenant"] == "t1"
    assert "timestamp" in payload


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    before = len(root.handlers)
    configure_logging("INFO", json_output=True)
    configure_logging("DEBUG", json_output=False)
    assert len(root.handlers) <= before + 1
    assert root.level == logging.DEBUG
    configure_logging("INFO", json_output=True)
