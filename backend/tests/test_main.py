"""Tests for the API entrypoint and privacy-safe logging."""

import json
import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from frequencia_ufmg.logging_config import JsonFormatter
from frequencia_ufmg.main import RequestLoggingMiddleware, app


def test_health_endpoint(caplog: pytest.LogCaptureFixture) -> None:
    """The health endpoint exposes a stable readiness contract."""

    response = TestClient(app).get("/health?secret=must-not-be-logged")

    assert response.status_code == 200
    assert len(response.headers["x-request-id"]) == 32
    assert response.json() == {
        "status": "ok",
        "service": "frequencia-ufmg",
        "version": "0.1.0",
    }
    request_record = next(record for record in caplog.records if record.msg == "request_completed")
    assert request_record.path == "/health"  # type: ignore[attr-defined]
    assert "must-not-be-logged" not in JsonFormatter().format(request_record)


def test_valid_request_id_is_propagated(caplog: pytest.LogCaptureFixture) -> None:
    """A safe caller-provided ID correlates client, service, and logs."""

    response = TestClient(app).get("/health", headers={"x-request-id": "client_request-42"})

    assert response.headers["x-request-id"] == "client_request-42"
    request_record = next(record for record in caplog.records if record.msg == "request_completed")
    assert request_record.request_id == "client_request-42"  # type: ignore[attr-defined]


def test_invalid_request_id_is_replaced() -> None:
    """Unbounded or malformed correlation values never enter structured logs."""

    invalid_request_id = "x" * 65
    response = TestClient(app).get("/health", headers={"x-request-id": invalid_request_id})

    assert response.headers["x-request-id"] != invalid_request_id
    assert len(response.headers["x-request-id"]) == 32


def test_request_failures_are_logged_without_request_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unhandled failures produce correlation metadata and no query values."""

    failing_app = FastAPI()
    failing_app.add_middleware(RequestLoggingMiddleware)

    @failing_app.get("/failure")
    def failure() -> None:
        raise RuntimeError("expected test failure")

    response = TestClient(failing_app, raise_server_exceptions=False).get(
        "/failure?token=never-log-this"
    )

    assert response.status_code == 500
    assert len(response.headers["x-request-id"]) == 32
    assert response.json() == {"detail": "Internal Server Error"}
    failure_record = next(record for record in caplog.records if record.msg == "request_failed")
    assert failure_record.status_code == 500  # type: ignore[attr-defined]
    assert "never-log-this" not in JsonFormatter().format(failure_record)


def test_json_formatter_serializes_plain_and_exception_records() -> None:
    """The formatter emits valid JSON and includes exceptions when present."""

    formatter = JsonFormatter()
    plain_record = logging.LogRecord("test", logging.INFO, __file__, 1, "ready", (), None)
    plain_payload = json.loads(formatter.format(plain_record))

    assert plain_payload["severity"] == "INFO"
    assert plain_payload["message"] == "ready"
    assert plain_payload["event"] is None
    assert "exception" not in plain_payload

    try:
        raise ValueError("formatted failure")
    except ValueError:
        exception_record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            "failed",
            (),
            sys.exc_info(),
        )

    exception_payload = json.loads(formatter.format(exception_record))
    assert "ValueError: formatted failure" in exception_payload["exception"]
