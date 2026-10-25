from datetime import UTC, datetime
from typing import Any

import pytest

from official_calendar_repository import OfficialCalendarSessionRepository
from session_service import InvalidSessionMutation

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


class Store:
    def __init__(self) -> None:
        self.commits: list[tuple[list[Any], list[Any]]] = []

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        assert segments == ("courses", "ele028", "sessions")
        return [self.get_user_document(*segments, "session-1")]

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        assert segments[-1] == "session-1"
        return {
            "name": "root/session-1",
            "fields": {
                "schemaVersion": {"integerValue": "1"},
                "startsAt": {"timestampValue": "2026-10-12T22:00:00Z"},
                "endsAt": {"timestampValue": "2026-10-12T23:40:00Z"},
                "lessonCount": {"integerValue": "2"},
                "callCount": {"integerValue": "1"},
                "firstPing": {"nullValue": None},
                "secondPing": {"nullValue": None},
                "attendanceStatus": {"nullValue": None},
                "absences": {"nullValue": None},
                "calendarStatus": {"stringValue": "scheduled"},
                "assessmentTitle": {"nullValue": None},
                "createdAt": {"timestampValue": "2026-10-01T12:00:00Z"},
                "updatedAt": {"timestampValue": "2026-10-01T12:00:00Z"},
            },
        }

    def commit_user_documents(self, *, updates: list[Any], deletes: list[Any]) -> None:
        self.commits.append((updates, deletes))


def test_lists_sessions_and_applies_holidays_atomically() -> None:
    store = Store()
    repository = OfficialCalendarSessionRepository(store, now=lambda: NOW)  # type: ignore[arg-type]

    sessions = repository.list_sessions("ele028")
    repository.apply_holidays([("ele028", "session-1")])

    assert sessions[0]["calendar_status"] == "scheduled"
    updates, deletes = store.commits[0]
    assert deletes == []
    assert updates[0][0] == ("courses", "ele028", "sessions", "session-1")
    assert updates[0][1]["calendarStatus"] == {"stringValue": "holiday"}
    assert updates[0][1]["updatedAt"] == {"timestampValue": "2026-10-12T12:00:00Z"}


def test_apply_rejects_a_candidate_changed_after_preview() -> None:
    store = Store()
    original = store.get_user_document

    def changed(*segments: str) -> dict[str, Any]:
        document = original(*segments)
        document["fields"]["calendarStatus"] = {"stringValue": "cancelled"}
        return document

    store.get_user_document = changed  # type: ignore[method-assign]
    repository = OfficialCalendarSessionRepository(store, now=lambda: NOW)  # type: ignore[arg-type]

    with pytest.raises(InvalidSessionMutation):
        repository.apply_holidays([("ele028", "session-1")])
    assert store.commits == []
