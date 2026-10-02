import json
from dataclasses import dataclass, field
from typing import Any

import pytest

import main as function


@dataclass
class FakeRequest:
    method: str
    path: str
    body_json: dict[str, Any] = field(default_factory=dict)
    body_binary: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class FakeResponse:
    def json(self, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
        return {"body": body, "status": status}


@dataclass
class FakeContext:
    req: FakeRequest
    res: FakeResponse = field(default_factory=FakeResponse)
    logs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.logs.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


def test_health_reads_tablesdb_and_reports_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "_read_probe_value", lambda _headers: "ready")
    monkeypatch.setenv("APPWRITE_FUNCTION_REGION", "nyc")
    context = FakeContext(FakeRequest("GET", "/health"))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["database"] == "ready"
    assert result["body"]["runtime"]["region"] == "nyc"
    assert result["body"]["handler_ms"] >= 0
    assert json.loads(context.logs[0])["event"] == "health_probe_completed"


def test_health_sanitizes_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_headers: dict[str, str]) -> str:
        raise RuntimeError("secret-token")

    monkeypatch.setattr(function, "_read_probe_value", fail)
    context = FakeContext(FakeRequest("GET", "/health"))

    result = function.main(context)

    assert result == {"body": {"error": "database_unavailable"}, "status": 503}
    assert context.errors == ['{"event":"database_probe_failed"}']
    assert "secret-token" not in "".join(context.errors)


def test_domain_route_calculates_absences() -> None:
    context = FakeContext(
        FakeRequest(
            "POST",
            "/domain",
            body_json={"status": "saiu_mais_cedo", "lessons": 4, "calls": 2},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["absences"] == 2
    assert json.loads(context.logs[0])["event"] == "domain_probe_completed"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "unknown", "lessons": 2, "calls": 1},
        {"status": "presente"},
        {"status": "presente", "lessons": "2", "calls": 1},
    ],
)
def test_domain_route_rejects_invalid_payload(body: dict[str, Any]) -> None:
    context = FakeContext(FakeRequest("POST", "/domain", body_json=body))

    assert function.main(context) == {"body": {"error": "invalid_request"}, "status": 400}
    assert context.errors == ['{"event":"domain_probe_rejected"}']


def test_pdf_route_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "extract_pdf_summary", lambda _payload: {"pages": 1})
    context = FakeContext(FakeRequest("POST", "/pdf", body_binary=b"%PDF-test"))

    result = function.main(context)

    assert result["body"]["summary"] == {"pages": 1}
    assert json.loads(context.logs[0])["event"] == "pdf_probe_completed"


def test_pdf_route_sanitizes_invalid_file(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_payload: bytes) -> dict[str, int]:
        raise ValueError("contains private academic content")

    monkeypatch.setattr(function, "extract_pdf_summary", fail)
    context = FakeContext(FakeRequest("POST", "/pdf", body_binary=b"private"))

    assert function.main(context) == {"body": {"error": "invalid_pdf"}, "status": 400}
    assert context.errors == ['{"event":"pdf_probe_rejected"}']
    assert "private academic content" not in "".join(context.errors)


def test_unknown_route_returns_not_found() -> None:
    context = FakeContext(FakeRequest("GET", "/unknown"))

    assert function.main(context) == {"body": {"error": "not_found"}, "status": 404}


def test_read_probe_value_uses_injected_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    class FakeClient:
        def set_endpoint(self, value: str) -> "FakeClient":
            calls["endpoint"] = value
            return self

        def set_project(self, value: str) -> "FakeClient":
            calls["project"] = value
            return self

        def set_key(self, value: str) -> "FakeClient":
            calls["key"] = value
            return self

    class FakeRow:
        data = {"value": "ready"}

    class FakeTablesDB:
        def __init__(self, client: FakeClient) -> None:
            calls["client"] = client

        def get_row(self, database_id: str, table_id: str, row_id: str) -> FakeRow:
            calls["row"] = (database_id, table_id, row_id)
            return FakeRow()

    monkeypatch.setattr(function, "Client", FakeClient)
    monkeypatch.setattr(function, "TablesDB", FakeTablesDB)
    monkeypatch.setattr(
        function,
        "environ",
        {
            "APPWRITE_FUNCTION_API_ENDPOINT": "https://nyc.cloud.appwrite.io/v1",
            "APPWRITE_FUNCTION_PROJECT_ID": "project",
            "SPIKE_DATABASE_ID": "database",
            "SPIKE_TABLE_ID": "table",
            "SPIKE_ROW_ID": "row",
        },
    )

    value = function._read_probe_value({"x-appwrite-key": "ephemeral"})

    assert value == "ready"
    assert calls["row"] == ("database", "table", "row")
    assert calls["key"] == "ephemeral"

    FakeRow.data = {"value": None}
    with pytest.raises(RuntimeError, match="invalid probe row"):
        function._read_probe_value({"X-Appwrite-Key": "ephemeral"})


def test_read_probe_value_requires_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "environ", {})

    with pytest.raises(RuntimeError, match="runtime configuration missing"):
        function._read_probe_value({})
