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
        self.patches: list[tuple[tuple[str, ...], dict[str, Any], tuple[str, ...]]] = []

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        self.reads.append(segments)
        return self.document

    def patch_user_document(
        self,
        *segments: str,
        fields: dict[str, Any],
        update_mask: tuple[str, ...],
    ) -> dict[str, Any]:
        self.patches.append((segments, fields, update_mask))
        return {"fields": fields}


def _repository(store: FakeFirestore) -> SessionMutationRepository:
    return SessionMutationRepository(store, now=lambda: NOW)  # type: ignore[arg-type]


def test_save_attendance_updates_only_authoritative_fields() -> None:
    store = FakeFirestore()

    result = _repository(store).save_attendance(
        "poo",
        SESSION_ID,
        {"status": "chegou_atrasado"},
    )

    assert store.reads == [("courses", "poo", "sessions", SESSION_ID)]
    path, fields, update_mask = store.patches[0]
    assert path == ("courses", "poo", "sessions", SESSION_ID)
    assert update_mask == ("attendanceStatus", "absences", "updatedAt")
    assert set(fields) == set(update_mask)
    assert fields["attendanceStatus"] == {"stringValue": "chegou_atrasado"}
    assert fields["absences"] == {"integerValue": "1"}
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

    _, fields, update_mask = store.patches[0]
    assert update_mask == ("calendarStatus", "updatedAt")
    assert set(fields) == set(update_mask)
    assert fields["calendarStatus"] == {"stringValue": "no_call"}
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
    assert store.patches == []
