from dataclasses import dataclass
from typing import Any

import pytest

from moodle_date_import import MoodleDateImportService, _matches, _months
from ufmg_session_store import UFMGReauthenticationRequired


@dataclass
class _Session:
    token: str = "private-token"


class _Sessions:
    def __init__(self, session: _Session | None | object = ...) -> None:
        self.session = _Session() if session is ... else session
        self.deleted = False

    def load(self, user_id: str, *, now: int) -> _Session | None:
        assert user_id == "user"
        assert now == 123
        return self.session

    def delete(self, user_id: str) -> None:
        assert user_id == "user"
        self.deleted = True


class _Courses:
    def list_courses(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "dcc203",
                "code": "DCC203",
                "name": "Programação Orientada a Objetos",
                "term": "2026-2",
                "starts_on": "2026-07-01T00:00:00Z",
                "ends_on": "2026-12-31T00:00:00Z",
            },
            {
                "id": "la631",
                "code": "LA631",
                "name": "Língua Alemã I",
                "term": "2026-2",
                "starts_on": "2026-07-01T00:00:00Z",
                "ends_on": "2026-12-31T00:00:00Z",
            },
        ]


class _Client:
    def __init__(self, events: list[dict[str, str]] | Exception) -> None:
        self.events = events
        self.months: list[tuple[int, int]] = []
        self.terms: list[str] = []

    def fetch(
        self, token: str, *, term: str, months: list[tuple[int, int]]
    ) -> list[dict[str, str]]:
        assert token == "private-token"
        self.terms.append(term)
        self.months = months
        if isinstance(self.events, Exception):
            raise self.events
        return self.events


class _Dates:
    def __init__(self) -> None:
        self.imports: list[tuple[str, list[dict[str, object]]]] = []

    def import_moodle_dates(
        self, course_id: str, events: list[dict[str, object]]
    ) -> dict[str, int]:
        self.imports.append((course_id, events))
        return {"total": len(events), "created": len(events), "updated": 0, "unchanged": 0}


def _event(**changes: str) -> dict[str, str]:
    return {
        "source_id": "910",
        "title": "Trabalho prático",
        "due_at": "2026-10-22T23:00:00Z",
        "moodle_course_id": "3701",
        "course_shortname": "DCC203 - POO",
        "course_fullname": "Programação Orientada a Objetos",
        "kind": "assignment",
        **changes,
    }


def test_import_matches_local_courses_and_reports_unmatched_events() -> None:
    sessions = _Sessions()
    client = _Client(
        [
            _event(),
            _event(source_id="911", course_shortname="Alemão LA631", kind="event"),
            _event(source_id="912", course_shortname="Curso sem código"),
        ]
    )
    dates = _Dates()
    service = MoodleDateImportService(sessions, client, _Courses(), dates)

    result = service.import_dates("user", now=123)

    assert client.months == [
        (2026, 7),
        (2026, 8),
        (2026, 9),
        (2026, 10),
        (2026, 11),
        (2026, 12),
    ]
    assert client.terms == ["2026-2"]
    assert [
        (course, [event["source_id"] for event in events]) for course, events in dates.imports
    ] == [
        ("dcc203", ["910"]),
        ("la631", ["911"]),
    ]
    assert result == {
        "total": 3,
        "matched": 2,
        "unmatched": 1,
        "created": 2,
        "updated": 0,
        "unchanged": 0,
    }


def test_import_does_not_guess_when_two_codes_match() -> None:
    dates = _Dates()
    service = MoodleDateImportService(
        _Sessions(),
        _Client([_event(course_shortname="DCC203 com LA631")]),
        _Courses(),
        dates,
    )

    result = service.import_dates("user", now=123)

    assert dates.imports == []
    assert result["unmatched"] == 1


def test_import_requires_a_saved_session_and_deletes_rejected_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleDateImportService(_Sessions(None), _Client([]), _Courses(), _Dates()).import_dates(
            "user", now=123
        )

    sessions = _Sessions()
    service = MoodleDateImportService(
        sessions,
        _Client(UFMGReauthenticationRequired()),
        _Courses(),
        _Dates(),
    )
    with pytest.raises(UFMGReauthenticationRequired):
        service.import_dates("user", now=123)
    assert sessions.deleted is True


def test_import_uses_term_fallback_and_rejects_an_unbounded_range() -> None:
    class Courses:
        def list_courses(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": "x",
                    "code": "ABC1",
                    "name": "X",
                    "term": "2026-2",
                    "starts_on": None,
                    "ends_on": None,
                }
            ]

    client = _Client([])
    service = MoodleDateImportService(_Sessions(), client, Courses(), _Dates())
    service.import_dates("user", now=123)
    assert client.months == [(2026, month) for month in range(7, 13)]

    class TooMany:
        def list_courses(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": str(year),
                    "code": f"ABC{year}",
                    "name": "X",
                    "term": f"{year}-1",
                    "starts_on": None,
                    "ends_on": None,
                }
                for year in (2024, 2025, 2026)
            ]

    with pytest.raises(ValueError):
        MoodleDateImportService(_Sessions(), _Client([]), TooMany(), _Dates()).import_dates(
            "user", now=123
        )


def test_matcher_rejects_missing_course_code() -> None:
    assert _matches(_event(), {"code": None}) is False


def test_import_rejects_a_course_with_an_invalid_term() -> None:
    class Courses:
        def list_courses(self) -> list[dict[str, Any]]:
            return [{"id": "x", "code": "ABC1", "term": "invalid"}]

    with pytest.raises(ValueError):
        MoodleDateImportService(_Sessions(), _Client([]), Courses(), _Dates()).import_dates(
            "user", now=123
        )


@pytest.mark.parametrize(
    "courses",
    [
        [],
        [{"term": "bad", "starts_on": None, "ends_on": None}],
        [
            {
                "term": "2026-2",
                "starts_on": "2026-07-01T00:00:00",
                "ends_on": "2026-12-31T00:00:00Z",
            }
        ],
    ],
)
def test_month_builder_rejects_missing_invalid_and_timezone_free_ranges(
    courses: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError):
        _months(courses)
