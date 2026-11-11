"""Tests for the API entrypoint and privacy-safe logging."""

import json
import logging
import sys

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from frequencia_ufmg.logging_config import (
    JsonFormatter,
    TelemetryDeduplicator,
    TelemetryKey,
    TelemetryRecorder,
)
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


# ==================== Sessão 55,35 - Testes de Telemetria ====================


class TestTelemetryDeduplicator:
    """Testes para o deduplicador de telemetria."""

    def test_chave_unica_gerada_corretamente(self) -> None:
        """TelemetryKey gera hash estável para a mesma entrada."""

        key1 = TelemetryKey("attendance", "record", "session", "aula-01")
        key2 = TelemetryKey("attendance", "record", "session", "aula-01")
        key3 = TelemetryKey("attendance", "record", "session", "aula-02")

        assert key1.to_hash() == key2.to_hash()
        assert key1.to_hash() != key3.to_hash()

    def test_primeiro_relatorio_eh_permitido(self) -> None:
        """O primeiro relatório de uma chave é sempre permitido."""

        deduplicator = TelemetryDeduplicator()
        key = TelemetryKey("attendance", "record", "session", "aula-01")

        assert deduplicator.should_report(key) is True

    def test_relatorio_duplicado_na_janela_eh_bloqueado(self) -> None:
        """Relatórios duplicados dentro da janela são bloqueados."""

        deduplicator = TelemetryDeduplicator(window_seconds=1.0)
        key = TelemetryKey("attendance", "record", "session", "aula-01")

        # Primeiro relatório
        assert deduplicator.should_report(key) is True
        # Segundo relatório na mesma janela
        assert deduplicator.should_report(key) is False

    def test_relatorio_fora_da_janela_eh_permitido(self) -> None:
        """Relatórios fora da janela de tempo são permitidos."""

        import time

        deduplicator = TelemetryDeduplicator(window_seconds=0.1)
        key = TelemetryKey("attendance", "record", "session", "aula-01")

        # Primeiro relatório
        assert deduplicator.should_report(key) is True
        # Esperar janela expirar
        time.sleep(0.15)
        # Segundo relatório após janela
        assert deduplicator.should_report(key) is True


class TestTelemetryRecorder:
    """Testes para o gravador de telemetria."""

    def test_gravacao_de_relatorio_unico(self) -> None:
        """Relatórios únicos são gravados com sucesso."""

        recorder = TelemetryRecorder()

        resultado = recorder.record(
            category="attendance",
            action="record",
            entity_type="session",
            entity_id="aula-01",
        )

        assert resultado is True

    def test_gravacao_de_relatorio_duplicado_eh_bloqueada(self) -> None:
        """Relatórios duplicados não são gravados."""

        recorder = TelemetryRecorder(TelemetryDeduplicator(window_seconds=1.0))

        # Primeiro relatório
        assert recorder.record("attendance", "record", "session", "aula-01") is True
        # Segundo relatório idêntico
        assert recorder.record("attendance", "record", "session", "aula-01") is False

    def test_gravacao_de_429(self) -> None:
        """Erro 429 é registrado corretamente."""

        recorder = TelemetryRecorder()

        info = recorder.record_429(
            request_id="req-001",
            retry_after=60.0,
            context={"path": "/api/data"},
        )

        assert info["error_code"] == "RATE_LIMITED"
        assert info["request_id"] == "req-001"
        assert info["retry_after"] == 60.0
        assert "timestamp" in info

    def test_gravacao_de_resource_exhausted(self) -> None:
        """Erro RESOURCE_EXHAUSTED é registrado corretamente."""

        recorder = TelemetryRecorder()

        info = recorder.record_resource_exhausted(
            request_id="req-002",
            context={"operation": "write"},
        )

        assert info["error_code"] == "RESOURCE_EXHAUSTED"
        assert info["request_id"] == "req-002"
        assert "timestamp" in info

    def test_recuperacao_de_rate_limit(self) -> None:
        """Informações de rate limit podem ser recuperadas."""

        recorder = TelemetryRecorder()

        recorder.record_429("req-001", retry_after=30.0)
        info = recorder.get_rate_limit("req-001")

        assert info is not None
        assert info["error_code"] == "RATE_LIMITED"

    def test_recuperacao_de_rate_limit_inexistente(self) -> None:
        """Recuperar rate limit inexistente retorna None."""

        recorder = TelemetryRecorder()

        assert recorder.get_rate_limit("inexistente") is None


class TestRateLimitPreservation:
    """Testes para preservação de erros 429 e RESOURCE_EXHAUSTED."""

    def test_429_preserva_contexto(self) -> None:
        """Contexto do erro 429 é preservado."""

        recorder = TelemetryRecorder()

        contexto = {
            "path": "/api/attendance",
            "method": "POST",
            "disciplina": "DCC203",
        }
        info = recorder.record_429("req-001", retry_after=120.0, context=contexto)

        assert info["context"] == contexto

    def test_multiplos_429_sao_armazenados(self) -> None:
        """Múltiplos erros 429 são armazenados separadamente."""

        recorder = TelemetryRecorder()

        recorder.record_429("req-001", retry_after=60.0)
        recorder.record_429("req-002", retry_after=120.0)

        info1 = recorder.get_rate_limit("req-001")
        info2 = recorder.get_rate_limit("req-002")

        assert info1 is not None
        assert info2 is not None
        assert info1 != info2
