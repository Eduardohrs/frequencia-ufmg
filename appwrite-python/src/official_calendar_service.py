"""Authenticated, bounded preview/apply flow for the official UFMG calendar."""

from collections.abc import Callable, Mapping
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

from official_calendar_reconciliation import preview_official_calendar

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_COURSES = 50
MAX_SESSIONS = 500
MAX_MONTHS = 12
MAX_CHANGES = 100


class InvalidOfficialCalendarRequest(ValueError):
    pass


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _Sessions(Protocol):
    def list_sessions(self, course_id: str) -> list[dict[str, Any]]: ...

    def apply_holidays(self, changes: list[tuple[str, str]]) -> None: ...


class _Calendar(Protocol):
    def fetch_month(self, year: int, month: int) -> dict[str, object]: ...


Telemetry = Callable[[str, Mapping[str, object]], None]


class OfficialCalendarService:
    def __init__(
        self,
        courses: _Courses,
        sessions: _Sessions,
        calendar: _Calendar,
        *,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._courses = courses
        self._sessions = sessions
        self._calendar = calendar
        self._telemetry = telemetry

    def preview(self) -> dict[str, object]:
        started = perf_counter()
        load_started = perf_counter()
        courses = self._courses.list_courses()
        if len(courses) > MAX_COURSES:
            raise InvalidOfficialCalendarRequest("too many courses")
        loaded: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        months: set[tuple[int, int]] = set()
        session_total = 0
        for course in courses:
            sessions = self._sessions.list_sessions(str(course["id"]))
            session_total += len(sessions)
            if session_total > MAX_SESSIONS:
                raise InvalidOfficialCalendarRequest("too many sessions")
            loaded.append((course, sessions))
            months.update(_month(session["starts_at"]) for session in sessions)
        if len(months) > MAX_MONTHS:
            raise InvalidOfficialCalendarRequest("too many calendar months")
        self._emit(
            "official_calendar_sessions_loaded",
            duration_ms=round((perf_counter() - load_started) * 1_000, 3),
            courses=len(courses),
            sessions=session_total,
            months=len(months),
        )

        fetch_started = perf_counter()
        fetched = {month: self._calendar.fetch_month(*month) for month in sorted(months)}
        self._emit(
            "official_calendar_months_fetched",
            duration_ms=round((perf_counter() - fetch_started) * 1_000, 3),
            months=len(months),
        )
        reconciliation_started = perf_counter()
        candidates: list[dict[str, object]] = []
        unchanged = protected = advisories = 0
        for course, sessions in loaded:
            by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
            for session in sessions:
                by_month.setdefault(_month(session["starts_at"]), []).append(session)
            for month, selected in by_month.items():
                calendar = fetched[month]
                result = preview_official_calendar(
                    calendar["events"], selected, source_url=str(calendar["source_url"])
                )
                preview_candidates = cast(list[dict[str, object]], result["candidates"])
                candidates.extend(
                    {
                        "course_id": course["id"],
                        "course_code": course["code"],
                        **candidate,
                    }
                    for candidate in preview_candidates
                )
                counts = cast(Mapping[str, int], result["counts"])
                unchanged += int(counts["unchanged"])
                protected += int(counts["protected"])
                advisories += int(counts["advisories"])
        candidates.sort(key=lambda item: (item["date"], item["course_code"], item["starts_at"]))
        result = {
            "candidates": candidates,
            "counts": {
                "candidates": len(candidates),
                "unchanged": unchanged,
                "protected": protected,
                "advisories": advisories,
            },
        }
        self._emit(
            "official_calendar_reconciliation_completed",
            duration_ms=round((perf_counter() - reconciliation_started) * 1_000, 3),
            candidates=len(candidates),
            unchanged=unchanged,
            protected=protected,
            advisories=advisories,
        )
        self._emit(
            "official_calendar_preview_completed",
            duration_ms=round((perf_counter() - started) * 1_000, 3),
            courses=len(courses),
            sessions=session_total,
            months=len(months),
            candidates=len(candidates),
        )
        return result

    def apply(self, payload: object) -> dict[str, int]:
        started = perf_counter()
        requested = _requested_changes(payload)
        preview = self.preview()
        available = {
            (str(item["course_id"]), str(item["session_id"]))
            for item in cast(list[dict[str, object]], preview["candidates"])
        }
        if not requested.issubset(available):
            raise InvalidOfficialCalendarRequest("stale official calendar changes")
        ordered = sorted(requested)
        self._sessions.apply_holidays(ordered)
        self._emit(
            "official_calendar_apply_completed",
            duration_ms=round((perf_counter() - started) * 1_000, 3),
            applied=len(ordered),
            skipped=0,
        )
        return {"applied": len(ordered), "skipped": 0}

    def _emit(self, event: str, **fields: object) -> None:
        if self._telemetry is not None:
            self._telemetry(event, fields)


def _month(value: object) -> tuple[int, int]:
    if not isinstance(value, str):
        raise InvalidOfficialCalendarRequest("invalid session date")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidOfficialCalendarRequest("invalid session date") from None
    local = instant.astimezone(SAO_PAULO)
    return local.year, local.month


def _requested_changes(payload: object) -> set[tuple[str, str]]:
    if not isinstance(payload, Mapping) or set(payload) != {"changes"}:
        raise InvalidOfficialCalendarRequest("invalid official calendar request")
    changes = payload["changes"]
    if not isinstance(changes, list) or not changes or len(changes) > MAX_CHANGES:
        raise InvalidOfficialCalendarRequest("invalid official calendar request")
    result: set[tuple[str, str]] = set()
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {"course_id", "session_id"}:
            raise InvalidOfficialCalendarRequest("invalid official calendar request")
        course_id, session_id = change["course_id"], change["session_id"]
        if not all(
            isinstance(value, str) and value and len(value) <= 128
            for value in (course_id, session_id)
        ):
            raise InvalidOfficialCalendarRequest("invalid official calendar request")
        result.add((course_id, session_id))
    if len(result) != len(changes):
        raise InvalidOfficialCalendarRequest("duplicate official calendar change")
    return result
