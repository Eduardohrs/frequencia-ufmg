"""Match Moodle's structured calendar events to local UFMG courses."""

import re
from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from time import monotonic
from typing import Any, Protocol, cast

from academic_sync_lineage import MOODLE_CALENDAR
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from sync_timing import Telemetry, _emit, timed_stage
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def fetch(
        self, token: str, *, term: str, months: list[tuple[int, int]]
    ) -> list[dict[str, str]]: ...


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _Dates(Protocol):
    def import_moodle_dates(
        self,
        course_id: str,
        events: list[dict[str, object]],
        *,
        complete: bool = False,
        covered_months: list[tuple[int, int]] | None = None,
    ) -> dict[str, int]: ...


class _CalendarState(Protocol):
    def load(self, term: str) -> dict[str, Any]: ...

    def save(
        self, term: str, *, fetched_at: int, months: list[tuple[int, int]]
    ) -> None: ...


class MoodleDateImportService:
    def __init__(
        self,
        sessions: _Sessions,
        client: _Client,
        courses: _Courses,
        dates: _Dates,
        *,
        calendar_state: _CalendarState | None = None,
        telemetry: Telemetry | None = None,
        persistence_workers: int = 1,
    ) -> None:
        if not 1 <= persistence_workers <= 8:
            raise ValueError("invalid date persistence concurrency")
        self._sessions = sessions
        self._client = client
        self._courses = courses
        self._dates = dates
        self._calendar_state = calendar_state
        self._telemetry = telemetry
        self._persistence_workers = persistence_workers

    def _last_fetched_at(self, term: str) -> int | None:
        if self._calendar_state is None:
            return None
        value = self._calendar_state.load(term).get("last_fetched_at")
        return value if type(value) is int and value > 0 else None

    def import_dates(self, user_id: str, *, now: int) -> dict[str, Any]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        courses = self._courses.list_courses()
        events: list[dict[str, str]] = []
        course_groups = _courses_by_term(courses)
        completed_terms: set[str] = set()
        covered: dict[str, list[tuple[int, int]]] = {}
        failed_sources: list[dict[str, object]] = []
        for term in sorted(course_groups):
            window = _fetch_window(term, self._last_fetched_at(term))
            covered[term] = window
            try:
                if window:
                    fetched = timed_stage(
                        "moodle_term_calendar",
                        partial(
                            self._client.fetch,
                            session.token,
                            term=term,
                            months=window,
                        ),
                        telemetry=self._telemetry,
                        fields={
                            "term": term,
                            "months": [[year, month] for year, month in window],
                            "full_term": window == _term_months(term),
                        },
                    )
                    events.extend({**event, "term": term} for event in fetched)
                    if self._calendar_state is not None:
                        self._calendar_state.save(term, fetched_at=now, months=window)
                completed_terms.add(term)
            except UFMGReauthenticationRequired:
                self._sessions.delete(user_id)
                raise
            except (MoodleUnavailable, InvalidMoodleResponse) as error:
                failed_sources.extend(
                    {
                        "course_id": course["id"],
                        "course_code": course["code"],
                        "stage": "calendar_fetch",
                        "reason": type(error).__name__,
                        "event_count": 0,
                    }
                    for course in course_groups[term]
                )

        if len(events) > 500:
            raise InvalidMoodleResponse("calendar_event_limit")
        course_by_id = {str(course["id"]): course for course in courses}
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        unmatched = 0
        unmatched_events: list[dict[str, object]] = []
        unsafe_courses: set[str] = set()
        matching_started = monotonic()
        for event in events:
            matches = [course for course in courses if _matches(event, course)]
            if len(matches) != 1:
                unmatched += 1
                unsafe_courses.update(
                    str(course["id"]) for course in (matches or course_groups[event["term"]])
                )
                issue: dict[str, object] = {
                    "source_id": event["source_id"],
                    "title": event["title"][:120],
                    "term": event["term"],
                    "reason": "ambiguous_course" if matches else "course_not_found",
                    "moodle_course_id": event["moodle_course_id"],
                    "match_count": len(matches),
                }
                unmatched_events.append(issue)
                _emit(self._telemetry, "moodle_event_unmatched", issue)
                continue
            grouped[matches[0]["id"]].append(
                {key: event[key] for key in ("source_id", "title", "due_at", "kind")}
            )

        _emit(
            self._telemetry,
            "academic_sync_stage_completed",
            {
                "stage": "moodle_date_matching",
                "duration_ms": round((monotonic() - matching_started) * 1_000, 3),
                "event_count": len(events),
                "matched": len(events) - unmatched,
                "unmatched": unmatched,
                "unsafe_course_count": len(unsafe_courses),
                "consumer": "course_date_persistence",
            },
        )
        # Per-run histogram by stable source identity: how many calendar events
        # are activity deadlines (assignment/quiz) versus general events, and
        # how many distinct Moodle event ids the run actually processed.
        kind_counts: dict[str, int] = {"assignment": 0, "quiz": 0, "event": 0}
        for event in events:
            kind = event["kind"]
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        _emit(
            self._telemetry,
            "moodle_calendar_event_kinds",
            {
                "term_count": len(course_groups),
                "kinds": kind_counts,
                "total": len(events),
                "matched": len(events) - unmatched,
                "unmatched": unmatched,
                "unique_source_ids": len({event["source_id"] for event in events}),
                "consumer": "academic_dates_and_agenda",
            },
        )

        result: dict[str, Any] = {
            "total": len(events),
            "matched": len(events) - unmatched,
            "unmatched": unmatched,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
        }
        if unmatched_events:
            result["unmatched_events"] = unmatched_events
        failed_courses: list[dict[str, object]] = list(failed_sources)
        eligible = {
            str(course["id"]): course
            for course in courses
            if str(course["id"]) not in unsafe_courses and course["term"] in completed_terms
        }
        course_ids = sorted(set(grouped) | set(eligible))

        def persist_course(course_id: str) -> dict[str, object]:
            values = grouped.get(course_id, [])
            course = course_by_id[course_id]
            fields: Mapping[str, object] = {
                "course_id": course_id,
                "course_code": str(course["code"]),
                "event_count": len(values),
            }
            try:
                imported = timed_stage(
                    "moodle_course_dates",
                    partial(
                        self._dates.import_moodle_dates,
                        course_id,
                        values,
                        complete=course_id not in unsafe_courses,
                        covered_months=covered.get(
                            course["term"], _term_months(course["term"])
                        ),
                    ),
                    telemetry=self._telemetry,
                    fields=fields,
                )
            except Exception as error:
                return {
                    "failed": len(values),
                    "failed_course": {
                        "course_id": course_id,
                        "course_code": fields["course_code"],
                        "stage": "dates_persistence",
                        "reason": type(error).__name__,
                        "event_count": len(values),
                    },
                }
            return {"imported": imported}

        if self._persistence_workers == 1 or len(course_ids) <= 1:
            outcomes = [persist_course(course_id) for course_id in course_ids]
        else:
            with ThreadPoolExecutor(
                max_workers=min(self._persistence_workers, len(course_ids)),
                thread_name_prefix="moodle-date-persistence",
            ) as pool:
                futures = [pool.submit(persist_course, course_id) for course_id in course_ids]
                # Consume in course-id order so summaries and failure lists stay
                # deterministic even when Firestore calls finish out of order.
                outcomes = [future.result() for future in futures]

        for outcome in outcomes:
            result["failed"] = result.get("failed", 0) + int(cast(int, outcome.get("failed", 0)))
            failed_course = outcome.get("failed_course")
            if isinstance(failed_course, dict):
                failed_courses.append(failed_course)
            imported = outcome.get("imported")
            if not isinstance(imported, dict):
                continue
            for field in ("created", "updated", "unchanged"):
                result[field] += int(imported[field])
            if imported.get("removed", 0):
                result["removed"] = result.get("removed", 0) + int(imported["removed"])
        if failed_courses:
            result["failed_courses"] = failed_courses
        _emit(
            self._telemetry,
            "academic_sync_lineage",
            {
                **MOODLE_CALENDAR,
                "source": "moodle_calendar",
                "dataset": "calendar_events",
                "consumer": "agenda_and_course_dates",
                "extracted": result["total"],
                "matched": result["matched"],
                "unmatched": result["unmatched"],
                "created": result["created"],
                "updated": result["updated"],
                "unchanged": result["unchanged"],
                "removed": result.get("removed", 0),
                "failed_courses": len(failed_courses),
                "covered_terms": sorted(completed_terms),
            },
        )
        return result


def _matches(event: dict[str, str], course: dict[str, Any]) -> bool:
    if "term" in event and event["term"] != course.get("term"):
        return False
    code = course.get("code")
    if not isinstance(code, str):
        return False
    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", re.IGNORECASE)
    return any(
        pattern.search(event[field]) is not None
        for field in ("course_shortname", "course_fullname")
    )


def _courses_by_term(courses: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for course in courses:
        term = course.get("term")
        if not isinstance(term, str) or re.fullmatch(r"20[2-9][0-9]-[12]", term) is None:
            raise ValueError("invalid course term")
        groups[term].append(course)
    if not groups or len(groups) > 2:
        raise ValueError("invalid course term")
    return groups


def _term_months(term: str) -> list[tuple[int, int]]:
    # Callers use the semesters already validated by _courses_by_term.
    first = 1 if term.endswith("-1") else 7
    return [(int(term[:4]), month) for month in range(first, first + 6)]


_WINDOW_OVERLAP_MONTHS = 1


def _fetch_window(term: str, last_fetched_at: int | None) -> list[tuple[int, int]]:
    """Months still worth querying: from the last fetch (minus overlap) to term end."""
    all_months = _term_months(term)
    if last_fetched_at is None or last_fetched_at <= 0:
        return all_months
    anchor = datetime.fromtimestamp(last_fetched_at, UTC)
    floor_year, floor_month = anchor.year, anchor.month - _WINDOW_OVERLAP_MONTHS
    while floor_month <= 0:
        floor_month += 12
        floor_year -= 1
    return [month for month in all_months if month >= (floor_year, floor_month)]
