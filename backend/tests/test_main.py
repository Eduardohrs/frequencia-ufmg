"""Tests for the API entrypoint."""

from fastapi.testclient import TestClient

from frequencia_ufmg.main import app


def test_health_endpoint() -> None:
    """The health endpoint exposes a stable readiness contract."""

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "frequencia-ufmg",
        "version": "0.1.0",
    }

