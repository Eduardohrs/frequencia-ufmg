from datetime import UTC, datetime
from typing import Any

import pytest

from course_service import InvalidCourse
from session_repository import SessionMutationRepository

NOW = datetime(2026, 10, 8, 18, 30, tzinfo=UTC)
SESSION_ID = "2026-10-08--thursday-19"


def _fields(**overrides: Any) -> dict[str, Any]:
    return {
        "schemaVersion": {"integerValue": "1"},
        "startsAt": {"timestampValue": "2026-10-08T22:00:00Z"},
        "endsAt": {"timestampValue": "2026-10-08T23:40:00Z"},
        "lessonCount": {"integerValue": "2"},
        "callCount": {"integerValue": "2"},
        "firstPing": {"stringValue": "no_campus"},
        "secondPing": {"nullValue": None},
        "attendanceStatus": {"nullValue": None},
        "absences": {"nullValue": None},
        "calendarStatus": {"stringValue": "scheduled"},
        "assessmentTitle": {"stringValue": "Prova 1"},
        "createdAt": {"timestampValue": "2026-08-01T12:00:00Z"},
        "updatedAt": {"timestampValue": "2026-08-01T12:00:00Z"},
        **overrides,
    }


class FakeFirestore:
    def __init__(self) -> None:
        self.document = {"name": f"root/{SESSION_ID}", "fields": _fields()}
        self.reads: list[tuple[str, ...]] = []
        self.commits: list[tuple[list[Any], list[Any]]] = []

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        self.reads.append(segments)
        return self.document

    def commit_user_documents(self, *, updates: list[Any], deletes: list[Any]) -> None:
        self.commits.append((updates, deletes))


def _repository(store: FakeFirestore) -> SessionMutationRepository:
    return SessionMutationRepository(store, now=lambda: NOW)  # type: ignore[arg-type]


def test_save_attendance_reads_one_session_and_commits_one_complete_document() -> None:
    store = FakeFirestore()

    result = _repository(store).save_attendance(
        "poo",
        SESSION_ID,
        {"status": "chegou_atrasado"},
    )

    assert store.reads == [("courses", "poo", "sessions", SESSION_ID)]
    updates, deletes = store.commits[0]
    assert deletes == []
    path, fields = updates[0]
    assert path == ("courses", "poo", "sessions", SESSION_ID)
    assert fields["attendanceStatus"] == {"stringValue": "chegou_atrasado"}
    assert fields["absences"] == {"integerValue": "1"}
    assert fields["firstPing"] == {"stringValue": "no_campus"}
    assert fields["assessmentTitle"] == {"stringValue": "Prova 1"}
    assert result == {
        "status": "chegou_atrasado",
        "absences": 1,
        "updated_at": "2026-10-08T18:30:00Z",
    }


def test_save_calendar_status_preserves_attendance_fields() -> None:
    store = FakeFirestore()
    store.document["fields"] = _fields(
        attendanceStatus={"stringValue": "presente"},
        absences={"integerValue": "0"},
    )

    result = _repository(store).save_calendar_status(
        "poo",
        SESSION_ID,
        {"calendar_status": "no_call"},
    )

    fields = store.commits[0][0][0][1]
    assert fields["calendarStatus"] == {"stringValue": "no_call"}
    assert fields["attendanceStatus"] == {"stringValue": "presente"}
    assert fields["absences"] == {"integerValue": "0"}
    assert result == {
        "calendar_status": "no_call",
        "updated_at": "2026-10-08T18:30:00Z",
    }


@pytest.mark.parametrize("course_id,session_id", [("bad/id", SESSION_ID), ("poo", "bad/id")])
def test_repository_rejects_unsafe_identifiers_before_reading(
    course_id: str,
    session_id: str,
) -> None:
    store = FakeFirestore()

    with pytest.raises(InvalidCourse):
        _repository(store).save_attendance(course_id, session_id, {"status": "presente"})

    assert store.reads == []
    assert store.commits == []
