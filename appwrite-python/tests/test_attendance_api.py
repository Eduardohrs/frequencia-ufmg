"""Contract tests for the authoritative Python attendance API."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

import main as function
from attendance_service import InvalidAttendanceRequest, evaluate_attendance
from firebase_app_check import FirebaseAppIdentity
from firebase_identity import InvalidIdentity

SHARED_CASES = cast(
    dict[str, Any],
    json.loads(
        (Path(__file__).resolve().parents[2] / "shared" / "attendance_cases.json").read_text(
            encoding="utf-8"
        )
    ),
)["casos"]


@pytest.mark.parametrize("case", SHARED_CASES, ids=[case["id"] for case in SHARED_CASES])
def test_authenticated_api_matches_every_shared_attendance_case(
    case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deployed contract must use the same POO model as the Python project."""

    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2_000, "a" * 64),
    )
    monkeypatch.setattr(
        function,
        "_security_store",
        lambda _headers: type("Store", (), {"consume": lambda self, **kwargs: None})(),
    )
    monkeypatch.setattr(function, "time", lambda: 1_500)
    context = function_test_context(
        {
            "lessons": case["aulas"],
            "calls": case["chamadas"],
            "first_ping": case["primeiro_ping"],
            "second_ping": case["segundo_ping"],
        }
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"] == {
        "status": case["situacao"],
        "absences": case["faltas"],
    }
    assert json.loads(context.logs[-1]) == {"event": "attendance_evaluated"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"lessons": 2, "calls": 1, "first_ping": "fora"},
        {
            "lessons": True,
            "calls": 1,
            "first_ping": "fora",
            "second_ping": "fora",
        },
        {
            "lessons": 3,
            "calls": 1,
            "first_ping": "fora",
            "second_ping": "fora",
        },
        {
            "lessons": 2,
            "calls": 1,
            "first_ping": 1,
            "second_ping": "fora",
        },
        {
            "lessons": 2,
            "calls": 1,
            "first_ping": "private-invalid-state",
            "second_ping": "fora",
        },
        {"lessons": 2, "calls": 1, "status": 1},
        {
            "lessons": 2,
            "calls": 1,
            "first_ping": "fora",
            "second_ping": "fora",
            "unexpected": "private-value",
        },
    ],
)
def test_attendance_api_rejects_invalid_payload_without_logging_values(
    body: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2_000, "a" * 64),
    )
    monkeypatch.setattr(
        function,
        "_security_store",
        lambda _headers: type("Store", (), {"consume": lambda self, **kwargs: None})(),
    )
    monkeypatch.setattr(function, "time", lambda: 1_500)
    context = function_test_context(body)

    result = function.main(context)

    assert result["status"] == 400
    assert result["body"] == {"error": "invalid_request"}
    assert context.errors[-1] == '{"event":"attendance_rejected"}'
    assert "private" not in "".join(context.errors)


def test_attendance_api_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_headers: dict[str, str]) -> str:
        raise InvalidIdentity("private-token")

    monkeypatch.setattr(function, "_firebase_identity", reject)
    context = function_test_context(
        {
            "lessons": 2,
            "calls": 1,
            "first_ping": "fora",
            "second_ping": "fora",
        }
    )

    result = function.main(context)

    assert result["status"] == 401
    assert result["body"] == {"error": "unauthorized"}
    assert context.errors == ['{"event":"firebase_identity_rejected"}']
    assert "private-token" not in "".join(context.errors)


def test_attendance_service_rejects_non_object_payload() -> None:
    with pytest.raises(InvalidAttendanceRequest):
        evaluate_attendance([])


def test_attendance_api_sanitizes_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2_000, "a" * 64),
    )
    monkeypatch.setattr(
        function,
        "_security_store",
        lambda _headers: type("Store", (), {"consume": lambda self, **kwargs: None})(),
    )
    monkeypatch.setattr(function, "time", lambda: 1_500)

    def reject(_payload: object) -> dict[str, str | int | None]:
        raise json.JSONDecodeError("private malformed body", "private", 0)

    monkeypatch.setattr(function, "evaluate_attendance", reject)
    context = function_test_context({})

    result = function.main(context)

    assert result["status"] == 400
    assert result["body"] == {"error": "invalid_request"}
    assert context.errors[-1] == '{"event":"attendance_rejected"}'
    assert "private" not in "".join(context.errors)


def test_attendance_api_calculates_default_absences_from_manual_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2_000, "a" * 64),
    )
    monkeypatch.setattr(
        function,
        "_security_store",
        lambda _headers: type("Store", (), {"consume": lambda self, **kwargs: None})(),
    )
    monkeypatch.setattr(function, "time", lambda: 1_500)

    result = function.main(
        function_test_context(
            {"lessons": 4, "calls": 2, "status": "saiu_mais_cedo"}
        )
    )

    assert result["status"] == 200
    assert result["body"] == {"status": "saiu_mais_cedo", "absences": 2}


def function_test_context(body: dict[str, Any]) -> Any:
    """Reuse the Function boundary doubles without coupling production code to tests."""

    from test_main import FakeContext, FakeRequest

    return FakeContext(FakeRequest("POST", "/v1/attendance/evaluate", body_json=body))
