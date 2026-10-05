from datetime import UTC, datetime
from typing import Any

import pytest

from course_service import course_to_firestore
from schedule_repository import DestructiveScheduleChange, ScheduleRepository
from schedule_service import InvalidSchedule, ScheduleOverlap

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _course(course_id: str = "poo", code: str = "DCC203") -> dict[str, object]:
    return {
        "id": course_id,
        "code": code,
        "name": code,
        "workload": 1,
        "term": "2026-2",
        "starts_on": "2026-08-04T00:00:00Z",
        "ends_on": "2026-08-18T00:00:00Z",
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _meeting(meeting_id: str = "tuesday-19", start: int = 1140) -> dict[str, object]:
    return {
        "id": meeting_id,
        "weekday": 2,
        "start_minutes": start,
        "end_minutes": start + 100,
        "lesson_count": 2,
        "call_count": 1,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _session(day: int, *, attended: bool = False) -> dict[str, object]:
    return {
        "id": f"2026-08-{day:02}--tuesday-19",
        "starts_at": f"2026-08-{day:02}T22:00:00Z",
        "ends_at": f"2026-08-{day:02}T23:40:00Z",
        "lesson_count": 2,
        "call_count": 1,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": "presente" if attended else None,
        "absences": 0 if attended else None,
        "calendar_status": "scheduled",
        "assessment_title": None,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _document(identifier: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"name": f"root/{identifier}", "fields": fields}


def _meeting_fields(value: dict[str, object]) -> dict[str, Any]:
    return {
        "schemaVersion": {"integerValue": "1"},
        "weekday": {"integerValue": str(value["weekday"])},
        "startMinutes": {"integerValue": str(value["start_minutes"])},
        "endMinutes": {"integerValue": str(value["end_minutes"])},
        "lessonCount": {"integerValue": str(value["lesson_count"])},
        "callCount": {"integerValue": str(value["call_count"])},
        "createdAt": {"timestampValue": value["created_at"]},
        "updatedAt": {"timestampValue": value["updated_at"]},
    }


def _session_fields(value: dict[str, object]) -> dict[str, Any]:
    def nullable(item: object, kind: str) -> dict[str, Any]:
        return {"nullValue": None} if item is None else {kind: str(item)}

    return {
        "schemaVersion": {"integerValue": "1"},
        "startsAt": {"timestampValue": value["starts_at"]},
        "endsAt": {"timestampValue": value["ends_at"]},
        "lessonCount": {"integerValue": str(value["lesson_count"])},
        "callCount": {"integerValue": str(value["call_count"])},
        "firstPing": nullable(value["first_ping"], "stringValue"),
        "secondPing": nullable(value["second_ping"], "stringValue"),
        "attendanceStatus": nullable(value["attendance_status"], "stringValue"),
        "absences": nullable(value["absences"], "integerValue"),
        "calendarStatus": {"stringValue": value["calendar_status"]},
        "assessmentTitle": nullable(value["assessment_title"], "stringValue"),
        "createdAt": {"timestampValue": value["created_at"]},
        "updatedAt": {"timestampValue": value["updated_at"]},
    }


class FakeFirestore:
    def __init__(self, *, protected: bool = False, overlap: bool = False) -> None:
        courses = [_course()]
        if overlap:
            courses.append(_course("other", "MAT001"))
        self.courses = [_document(str(item["id"]), course_to_firestore(item)) for item in courses]
        self.meetings = {
            "poo": [_document("tuesday-19", _meeting_fields(_meeting()))],
            "other": [_document("other-meeting", _meeting_fields(_meeting("other-meeting")))],
        }
        self.sessions = {
            "poo": [
                _document(str(item["id"]), _session_fields(item))
                for item in (
                    _session(4, attended=protected),
                    _session(11),
                    _session(18),
                )
            ]
        }
        self.commits: list[tuple[list[Any], list[Any]]] = []

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        return next(item for item in self.courses if item["name"].endswith(segments[-1]))

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        if segments == ("courses",):
            return self.courses
        values = self.meetings if segments[-1] == "meetings" else self.sessions
        return values.get(segments[1], [])

    def commit_user_documents(self, *, updates: list[Any], deletes: list[Any]) -> None:
        self.commits.append((updates, deletes))


def _repository(store: FakeFirestore) -> ScheduleRepository:
    return ScheduleRepository(store, now=lambda: NOW)  # type: ignore[arg-type]


def test_get_schedule_is_a_read_only_noop_preview() -> None:
    store = FakeFirestore()

    result = _repository(store).get_schedule("poo")

    assert result["course"]["id"] == "poo"
    assert result["meetings"][0]["id"] == "tuesday-19"
    assert result["changes"] == {
        "meeting_upserts": 0,
        "meeting_deletes": 0,
        "session_upserts": 0,
        "session_deletes": 0,
        "destructive_deletes": 0,
    }
    assert store.commits == []


def test_save_schedule_commits_period_meetings_and_sessions_atomically() -> None:
    store = FakeFirestore()
    payload = {
        "starts_on": "2026-08-04T00:00:00Z",
        "ends_on": "2026-08-25T00:00:00Z",
        "meetings": [
            {
                "id": "tuesday-20",
                "weekday": 2,
                "start_minutes": 1200,
                "lesson_count": 2,
                "call_count": 1,
            }
        ],
        "confirm_destructive": False,
    }

    result = _repository(store).save_schedule("poo", payload)

    assert result["changes"] == {
        "meeting_upserts": 1,
        "meeting_deletes": 1,
        "session_upserts": 4,
        "session_deletes": 3,
        "destructive_deletes": 0,
    }
    updates, deletes = store.commits[0]
    assert len(updates) == 6
    assert len(deletes) == 4


def test_save_requires_confirmation_before_deleting_evidence() -> None:
    store = FakeFirestore(protected=True)
    payload = {
        "starts_on": None,
        "ends_on": None,
        "meetings": [],
        "confirm_destructive": False,
    }

    with pytest.raises(DestructiveScheduleChange) as caught:
        _repository(store).save_schedule("poo", payload)

    assert caught.value.count == 1
    assert store.commits == []
    payload["confirm_destructive"] = True
    _repository(store).save_schedule("poo", payload)
    assert len(store.commits) == 1


def test_save_rejects_overlap_with_another_active_course() -> None:
    store = FakeFirestore(overlap=True)
    payload = {
        "starts_on": "2026-08-04T00:00:00Z",
        "ends_on": "2026-08-18T00:00:00Z",
        "meetings": [
            {
                "id": "tuesday-19",
                "weekday": 2,
                "start_minutes": 1140,
                "lesson_count": 2,
                "call_count": 1,
            }
        ],
        "confirm_destructive": False,
    }

    with pytest.raises(ScheduleOverlap):
        _repository(store).save_schedule("poo", payload)

    assert store.commits == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"starts_on": None, "ends_on": None, "meetings": [], "confirm_destructive": 1},
    ],
)
def test_save_rejects_malformed_mutations(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidSchedule):
        _repository(FakeFirestore()).save_schedule("poo", payload)
