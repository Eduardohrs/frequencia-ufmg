"""HTTP contract tests for authoritative session mutations."""

import json
from typing import Any

import pytest
from test_main import FakeContext, FakeRequest

import main as function
from course_service import InvalidCourse
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreUnavailable,
)
from schedule_service import InvalidSchedule
from session_service import InactiveAttendanceSession, InvalidSessionMutation

ATTENDANCE_PATH = "/v1/courses/poo/sessions/session-1/attendance"
CALENDAR_PATH = "/v1/courses/poo/sessions/session-1/calendar-status"


class Repository:
    failure: Exception | None = None

    def save_attendance(
        self,
        course_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.failure is not None:
            raise self.failure
        assert (course_id, session_id, payload) == (
            "poo",
            "session-1",
            {"status": "presente"},
        )
        return {
            "status": "presente",
            "absences": 0,
            "updated_at": "2026-10-08T18:30:00Z",
        }

    def save_calendar_status(
        self,
        course_id: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if self.failure is not None:
            raise self.failure
        assert (course_id, session_id, payload) == (
            "poo",
            "session-1",
            {"calendar_status": "no_call"},
        )
        return {
            "calendar_status": "no_call",
            "updated_at": "2026-10-08T18:30:00Z",
        }


def _enable(monkeypatch: pytest.MonkeyPatch, repository: Repository) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(function, "_session_repository", lambda *_args: repository)
    monkeypatch.setenv("ENABLE_SESSION_WRITES", "true")


def test_put_attendance_persists_the_authoritative_decision_with_bounded_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, Repository())
    context = FakeContext(
        FakeRequest("PUT", ATTENDANCE_PATH, body_json={"status": "presente"})
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"] == {
        "status": "presente",
        "absences": 0,
        "updated_at": "2026-10-08T18:30:00Z",
    }
    assert json.loads(context.logs[0]) == {
        "event": "attendance_save_succeeded",
        "manual_correction": False,
    }


def test_put_calendar_status_persists_only_the_authoritative_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, Repository())
    context = FakeContext(
        FakeRequest(
            "PUT",
            CALENDAR_PATH,
            body_json={"calendar_status": "no_call"},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["calendar_status"] == "no_call"
    assert json.loads(context.logs[0]) == {"event": "calendar_status_save_succeeded"}


def test_session_write_switch_fails_closed_after_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "user", None

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.delenv("ENABLE_SESSION_WRITES", raising=False)

    result = function.main(FakeContext(FakeRequest("PUT", ATTENDANCE_PATH)))

    assert result["status"] == 503
    assert result["body"] == {"error": "session_writes_disabled"}
    assert routes == ["/v1/sessions/attendance/put"]


def test_session_mutation_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("PUT", ATTENDANCE_PATH))) is rejection


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (InactiveAttendanceSession(), 409, "attendance_inactive_session"),
        (InvalidSessionMutation(), 400, "session_mutation_rejected"),
        (InvalidCourse(), 400, "session_mutation_rejected"),
        (InvalidSchedule(), 500, "session_data_invalid"),
        (FirestoreRequestRejected(), 500, "session_data_invalid"),
        (FirestoreNotFound(), 404, "session_not_found"),
        (FirestoreAccessDenied(), 403, "session_access_denied"),
        (FirestoreUnavailable(), 503, "session_store_unavailable"),
    ],
)
def test_session_mutation_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository()
    repository.failure = failure
    _enable(monkeypatch, repository)
    context = FakeContext(
        FakeRequest("PUT", ATTENDANCE_PATH, body_json={"private": "value"})
    )

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    assert json.loads(context.errors[0]) == {"event": error}
    assert "private" not in "".join(context.errors)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/courses/poo/sessions/session-1",
        "/v1/courses/poo/sessions/session-1/unknown",
        "/v1/courses/poo/sessions/session-1/attendance/extra",
    ],
)
def test_unrecognized_session_mutation_paths_are_not_found(path: str) -> None:
    result = function.main(FakeContext(FakeRequest("POST", path)))

    assert result["status"] == 404
    assert result["body"] == {"error": "not_found"}


def test_session_repository_uses_the_shared_firestore_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object()
    monkeypatch.setattr(function, "_firestore", lambda *_args: client)
    monkeypatch.setattr(
        function,
        "SessionMutationRepository",
        lambda value: ("session", value),
    )

    assert function._session_repository({}, "user") == ("session", client)
