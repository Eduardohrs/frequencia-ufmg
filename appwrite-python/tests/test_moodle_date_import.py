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
        self, course_id: str, events: list[dict[str, object]], *, complete: bool = False
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
    assert {
        key: result[key]
        for key in ("total", "matched", "unmatched", "created", "updated", "unchanged")
    } == {
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

    assert not any(events for _, events in dates.imports)
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


def test_same_code_in_another_term_does_not_make_the_event_ambiguous() -> None:
    class Courses:
        def list_courses(self) -> list[dict[str, Any]]:
            return [
                dict(_Courses().list_courses()[0], id="past", term="2026-1"),
                _Courses().list_courses()[0],
            ]

    class Client(_Client):
        def fetch(
            self, token: str, *, term: str, months: list[tuple[int, int]]
        ) -> list[dict[str, str]]:
            return [_event()] if term == "2026-2" else []

    dates = _Dates()
    result = MoodleDateImportService(_Sessions(), Client([]), Courses(), dates).import_dates(
        "user", now=123
    )
    assert result["matched"] == 1
    assert [(course, len(events)) for course, events in dates.imports if events] == [("dcc203", 1)]


def test_persistence_failure_in_one_course_does_not_abort_the_other() -> None:
    class Dates(_Dates):
        def import_moodle_dates(
            self, course_id: str, events: list[dict[str, object]], *, complete: bool = False
        ) -> dict[str, int]:
            if course_id == "dcc203":
                raise OSError("synthetic persistence outage")
            return super().import_moodle_dates(course_id, events)

    dates = Dates()
    result = MoodleDateImportService(
        _Sessions(),
        _Client([_event(), _event(source_id="911", course_shortname="LA631")]),
        _Courses(),
        dates,
    ).import_dates("user", now=123)
    assert dates.imports[0][0] == "la631"
    assert result["created"] == 1


def test_failed_term_never_clears_its_courses_and_other_term_continues() -> None:
    from moodle_structured_dates import MoodleUnavailable

    class Courses:
        def list_courses(self):
            return [
                dict(_Courses().list_courses()[0], id="past", term="2026-1"),
                _Courses().list_courses()[0],
            ]

    class Client(_Client):
        def fetch(self, token, *, term, months):
            if term == "2026-1":
                raise MoodleUnavailable("temporary outage")
            return [_event()]

    dates = _Dates()
    logs = []
    result = MoodleDateImportService(
        _Sessions(),
        Client([]),
        Courses(),
        dates,
        telemetry=lambda event, fields: logs.append((event, fields)),
    ).import_dates("user", now=123)
    assert [course for course, _ in dates.imports] == ["dcc203"]
    assert result["created"] == 1
    assert result["failed_courses"][0]["stage"] == "calendar_fetch"
    failed = next(fields for event, fields in logs if event == "academic_sync_stage_failed")
    assert failed["term"] == "2026-1"
    assert failed["stage"] == "moodle_term_calendar"


def test_persisted_failures_report_exact_course_and_logging_failure_is_not_fatal() -> None:
    class Dates(_Dates):
        def import_moodle_dates(self, course_id, events, *, complete=False):
            if course_id == "dcc203":
                raise OSError("store failed")
            return {"created": 0, "updated": 0, "unchanged": 0, "removed": 1}

    logs = []

    def telemetry(event, fields):
        logs.append((event, fields))
        raise RuntimeError("logger offline")

    result = MoodleDateImportService(
        _Sessions(), _Client([_event()]), _Courses(), Dates(), telemetry=telemetry
    ).import_dates("user", now=123)
    assert result["failed"] == 1
    assert result["removed"] == 1
    assert result["failed_courses"][0]["course_code"] == "DCC203"
    assert any(
        event == "academic_sync_stage_failed" and fields["course_id"] == "dcc203"
        for event, fields in logs
    )


def test_global_event_limit_is_checked_before_any_persistence() -> None:
    from moodle_structured_dates import InvalidMoodleResponse

    dates = _Dates()
    with pytest.raises(InvalidMoodleResponse) as rejected:
        MoodleDateImportService(
            _Sessions(), _Client([_event(source_id=str(i)) for i in range(501)]), _Courses(), dates
        ).import_dates("user", now=123)
    assert rejected.value.reason == "calendar_event_limit"
    assert not dates.imports
