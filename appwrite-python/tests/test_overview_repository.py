from typing import Any

import pytest

from overview_repository import AcademicOverviewRepository, OverviewTooLarge


def _course(identifier: str, code: str) -> dict[str, Any]:
    return {
        "name": f"root/{identifier}",
        "fields": {
            "schemaVersion": {"integerValue": "1"},
            "code": {"stringValue": code},
            "name": {"stringValue": code},
            "workload": {"integerValue": "60"},
            "term": {"stringValue": "2026-2"},
            "startsOn": {"timestampValue": "2026-07-01T00:00:00Z"},
            "endsOn": {"timestampValue": "2026-12-31T00:00:00Z"},
            "createdAt": {"timestampValue": "2026-07-01T12:00:00Z"},
            "updatedAt": {"timestampValue": "2026-07-01T12:00:00Z"},
        },
    }


def _session(identifier: str, starts_at: str) -> dict[str, Any]:
    return {
        "name": f"root/{identifier}",
        "fields": {
            "schemaVersion": {"integerValue": "1"},
            "startsAt": {"timestampValue": starts_at},
            "endsAt": {"timestampValue": starts_at.replace("10:00", "11:40")},
            "lessonCount": {"integerValue": "2"},
            "callCount": {"integerValue": "1"},
            "firstPing": {"nullValue": None},
            "secondPing": {"nullValue": None},
            "attendanceStatus": {"nullValue": None},
            "absences": {"nullValue": None},
            "calendarStatus": {"stringValue": "scheduled"},
            "assessmentTitle": {"nullValue": None},
            "createdAt": {"timestampValue": "2026-07-01T12:00:00Z"},
            "updatedAt": {"timestampValue": "2026-07-01T12:00:00Z"},
        },
    }


class FakeFirestore:
    def __init__(self, courses: list[dict[str, Any]], sessions: dict[str, list[dict[str, Any]]]):
        self.courses = courses
        self.sessions = sessions
        self.calls: list[tuple[str, ...]] = []

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        self.calls.append(segments)
        if segments == ("courses",):
            return self.courses
        return self.sessions[segments[1]]


def test_overview_loads_each_course_sessions_once_and_orders_the_response() -> None:
    store = FakeFirestore(
        [_course("two", "MAT002"), _course("one", "MAT001")],
        {
            "one": [
                _session("later", "2026-10-09T10:00:00Z"),
                _session("earlier", "2026-10-08T10:00:00Z"),
            ],
            "two": [],
        },
    )

    result = AcademicOverviewRepository(store).load()  # type: ignore[arg-type]

    assert [item["course"]["id"] for item in result] == ["one", "two"]
    assert [session["id"] for session in result[0]["sessions"]] == ["earlier", "later"]
    assert set(store.calls) == {
        ("courses",),
        ("courses", "one", "sessions"),
        ("courses", "two", "sessions"),
    }
    assert len(store.calls) == 3


def test_overview_rejects_more_than_the_bounded_course_count() -> None:
    store = FakeFirestore(
        [_course(f"course-{index}", f"MAT{index:03}") for index in range(51)],
        {},
    )

    with pytest.raises(OverviewTooLarge):
        AcademicOverviewRepository(store).load()  # type: ignore[arg-type]

    assert store.calls == [("courses",)]


def test_overview_returns_empty_without_requesting_sessions() -> None:
    store = FakeFirestore([], {})

    assert AcademicOverviewRepository(store).load() == []  # type: ignore[arg-type]
    assert store.calls == [("courses",)]


def test_overview_rejects_more_than_the_bounded_session_count() -> None:
    store = FakeFirestore(
        [_course("one", "MAT001")],
        {"one": [_session(f"session-{index}", "2026-10-08T10:00:00Z") for index in range(501)]},
    )

    with pytest.raises(OverviewTooLarge):
        AcademicOverviewRepository(store).load()  # type: ignore[arg-type]
