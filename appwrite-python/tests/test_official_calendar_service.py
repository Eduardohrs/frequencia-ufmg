from datetime import datetime

import pytest

from official_calendar_service import (
    InvalidOfficialCalendarRequest,
    OfficialCalendarService,
)


def _session(identifier: str, starts_at: str, *, status: str = "scheduled") -> dict[str, object]:
    start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    end = start.replace(hour=23, minute=40)
    return {
        "id": identifier,
        "starts_at": starts_at,
        "ends_at": end.isoformat().replace("+00:00", "Z"),
        "calendar_status": status,
        "lesson_count": 2,
        "call_count": 1,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": None,
        "absences": None,
        "assessment_title": None,
        "created_at": "2026-10-01T12:00:00Z",
        "updated_at": "2026-10-01T12:00:00Z",
    }


class Courses:
    def list_courses(self) -> list[dict[str, str]]:
        return [
            {"id": "ele028", "code": "ELE028"},
            {"id": "mat001", "code": "MAT001"},
        ]


class Sessions:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str]] = []

    def list_sessions(self, course_id: str) -> list[dict[str, object]]:
        if course_id == "ele028":
            return [_session("a", "2026-10-12T22:00:00Z")]
        return [_session("b", "2026-10-13T22:00:00Z")]

    def apply_holidays(self, changes: list[tuple[str, str]]) -> None:
        self.saved = changes


class Calendar:
    def fetch_month(self, year: int, month: int) -> dict[str, object]:
        assert (year, month) == (2026, 10)
        return {
            "source_url": "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2026",
            "events": [
                {
                    "title": "Feriado: Nossa Senhora Aparecida",
                    "campus": "all",
                    "start_date": "2026-10-12",
                    "end_date": "2026-10-12",
                    "effect": "holiday",
                    "confidence": "official",
                }
            ],
        }


class ManyCourses:
    def list_courses(self) -> list[dict[str, str]]:
        return [{"id": str(index), "code": str(index)} for index in range(51)]


class ManySessions:
    def list_sessions(self, _course_id: str) -> list[dict[str, object]]:
        return [_session(str(index), "2026-10-12T22:00:00Z") for index in range(501)]

    def apply_holidays(self, _changes: list[tuple[str, str]]) -> None:
        raise AssertionError


class ManyMonths:
    def list_sessions(self, _course_id: str) -> list[dict[str, object]]:
        result = []
        for index in range(13):
            year, month = 2026 + index // 12, index % 12 + 1
            result.append(_session(str(index), f"{year:04d}-{month:02d}-12T22:00:00Z"))
        return result

    def apply_holidays(self, _changes: list[tuple[str, str]]) -> None:
        raise AssertionError


def test_preview_decorates_candidates_and_fetches_each_month_once() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    service = OfficialCalendarService(
        Courses(),
        Sessions(),
        Calendar(),
        telemetry=lambda name, fields: events.append((name, dict(fields))),
    )

    result = service.preview()

    assert result["candidates"] == [
        {
            "course_id": "ele028",
            "course_code": "ELE028",
            "session_id": "a",
            "date": "2026-10-12",
            "starts_at": "2026-10-12T22:00:00Z",
            "ends_at": "2026-10-12T23:40:00Z",
            "from": "scheduled",
            "to": "holiday",
            "events": [
                {
                    "title": "Feriado: Nossa Senhora Aparecida",
                    "source_url": "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2026",
                    "confidence": "official",
                }
            ],
        }
    ]
    assert result["counts"]["candidates"] == 1
    completed = [fields for name, fields in events if name == "official_calendar_preview_completed"]
    assert completed[0]["months"] == 1
    assert completed[0]["duration_ms"] >= 0


def test_apply_recomputes_candidates_and_only_writes_requested_changes() -> None:
    sessions = Sessions()
    service = OfficialCalendarService(Courses(), sessions, Calendar())

    result = service.apply({"changes": [{"course_id": "ele028", "session_id": "a"}]})

    assert sessions.saved == [("ele028", "a")]
    assert result == {"applied": 1, "skipped": 0}


def test_confirmed_holiday_disappears_from_next_preview_and_preserves_other_sessions() -> None:
    class PersistentSessions(Sessions):
        def __init__(self) -> None:
            super().__init__()
            self.rows = {
                "ele028": [_session("a", "2026-10-12T22:00:00Z")],
                "mat001": [_session("b", "2026-10-12T22:00:00Z", status="no_call")],
            }

        def list_sessions(self, course_id: str) -> list[dict[str, object]]:
            return self.rows[course_id]

        def apply_holidays(self, changes: list[tuple[str, str]]) -> None:
            super().apply_holidays(changes)
            for course_id, session_id in changes:
                row = next(item for item in self.rows[course_id] if item["id"] == session_id)
                row["calendar_status"] = "holiday"

    sessions = PersistentSessions()
    original_protected = dict(sessions.rows["mat001"][0])
    service = OfficialCalendarService(Courses(), sessions, Calendar())
    assert service.preview()["counts"]["candidates"] == 1
    service.apply({"changes": [{"course_id": "ele028", "session_id": "a"}]})
    assert service.preview()["candidates"] == []
    assert sessions.rows["mat001"][0] == original_protected
    assert sessions.rows["ele028"][0]["attendance_status"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"changes": []},
        {"changes": [{"course_id": "ele028", "session_id": "missing"}]},
        {"changes": [{"course_id": "ele028", "session_id": "a", "extra": True}]},
    ],
)
def test_apply_rejects_empty_invalid_or_stale_requests(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidOfficialCalendarRequest):
        OfficialCalendarService(Courses(), Sessions(), Calendar()).apply(payload)


@pytest.mark.parametrize(
    "courses,sessions",
    [(ManyCourses(), Sessions()), (Courses(), ManySessions()), (Courses(), ManyMonths())],
)
def test_preview_rejects_unbounded_data(courses: object, sessions: object) -> None:
    with pytest.raises(InvalidOfficialCalendarRequest):
        OfficialCalendarService(courses, sessions, Calendar()).preview()  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [None, "not-a-date"])
def test_preview_rejects_invalid_session_dates(value: object) -> None:
    class InvalidSessions(Sessions):
        def list_sessions(self, _course_id: str) -> list[dict[str, object]]:
            return [{"starts_at": value}]

    with pytest.raises(InvalidOfficialCalendarRequest):
        OfficialCalendarService(Courses(), InvalidSessions(), Calendar()).preview()


@pytest.mark.parametrize(
    "changes",
    [
        [{"course_id": "", "session_id": "a"}],
        [{"course_id": "ele028", "session_id": "a"}] * 2,
        [{"course_id": "ele028", "session_id": "a"}] * 101,
    ],
)
def test_apply_rejects_unsafe_duplicate_or_unbounded_changes(changes: list[object]) -> None:
    with pytest.raises(InvalidOfficialCalendarRequest):
        OfficialCalendarService(Courses(), Sessions(), Calendar()).apply({"changes": changes})
