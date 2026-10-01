from io import BytesIO
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from worker import app


class FakePreparedStatement:
    async def first(self) -> SimpleNamespace:
        return SimpleNamespace(ok=1)


class FakeDatabase:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def prepare(self, query: str) -> FakePreparedStatement:
        self.queries.append(query)
        return FakePreparedStatement()


class InjectEnvironment:
    def __init__(self, application: object, database: FakeDatabase) -> None:
        self.application = application
        self.database = database

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        scope["env"] = SimpleNamespace(DB=self.database)
        await self.application(scope, receive, send)  # type: ignore[operator]


def client_with_database() -> tuple[TestClient, FakeDatabase]:
    database = FakeDatabase()
    return TestClient(InjectEnvironment(app, database)), database


def test_health_proves_fastapi_and_d1_are_connected() -> None:
    client, database = client_with_database()

    response = client.get("/v1/spike/health")

    assert response.status_code == 200
    assert response.json() == {"d1": True, "runtime": "python", "status": "ok"}
    assert database.queries == ["SELECT 1 AS ok"]


def test_domain_endpoint_runs_the_attendance_rule() -> None:
    client, database = client_with_database()

    response = client.post(
        "/v1/spike/domain",
        json={"status": "chegou_atrasado", "lessons": 4, "calls": 2},
    )

    assert response.status_code == 200
    assert response.json() == {"absences": 2, "d1": True}
    assert database.queries == ["SELECT 1 AS ok"]


def test_domain_endpoint_turns_invalid_combinations_into_a_client_error() -> None:
    client, _ = client_with_database()

    response = client.post(
        "/v1/spike/domain",
        json={"status": "presente", "lessons": 1, "calls": 2},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid session configuration"}


def test_pdf_endpoint_extracts_a_pdf_in_memory() -> None:
    client, _ = client_with_database()
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)

    response = client.post(
        "/v1/spike/pdf",
        content=buffer.getvalue(),
        headers={"content-type": "application/pdf"},
    )

    assert response.status_code == 200
    assert response.json()["pages"] == 1


def test_pdf_endpoint_rejects_the_wrong_media_type() -> None:
    client, _ = client_with_database()

    response = client.post(
        "/v1/spike/pdf",
        content=b"not a pdf",
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "application/pdf required"}


def test_pdf_endpoint_returns_a_safe_error_for_invalid_pdf_bytes() -> None:
    client, _ = client_with_database()

    response = client.post(
        "/v1/spike/pdf",
        content=b"not a pdf",
        headers={"content-type": "application/pdf"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid PDF signature"}
