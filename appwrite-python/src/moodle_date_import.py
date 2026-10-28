"""Match Moodle's structured calendar events to local UFMG courses."""

import re
from collections import defaultdict
from collections.abc import Mapping
from functools import partial
from typing import Any, Protocol

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


class MoodleDateImportService:
    def __init__(
        self,
        sessions: _Sessions,
        client: _Client,
        courses: _Courses,
        dates: _Dates,
        *,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._courses = courses
        self._dates = dates
        self._telemetry = telemetry

    def import_dates(self, user_id: str, *, now: int) -> dict[str, Any]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        courses = self._courses.list_courses()
        events: list[dict[str, str]] = []
        course_groups = _courses_by_term(courses)
        completed_terms: set[str] = set()
        failed_sources: list[dict[str, object]] = []
        for term in sorted(course_groups):
            try:
                fetched = timed_stage(
                    "moodle_term_calendar",
                    partial(
                        self._client.fetch,
                        session.token,
                        term=term,
                        months=_term_months(term),
                    ),
                    telemetry=self._telemetry,
                    fields={"term": term},
                )
                events.extend({**event, "term": term} for event in fetched)
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
        for course_id in sorted(set(grouped) | set(eligible)):
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
                        covered_months=_term_months(course["term"]),
                    ),
                    telemetry=self._telemetry,
                    fields=fields,
                )
            except Exception as error:
                result["failed"] = result.get("failed", 0) + len(values)
                failed_courses.append(
                    {
                        "course_id": course_id,
                        "course_code": fields["course_code"],
                        "stage": "dates_persistence",
                        "reason": type(error).__name__,
                        "event_count": len(values),
                    }
                )
                continue
            for field in ("created", "updated", "unchanged"):
                result[field] += imported[field]
            if imported.get("removed", 0):
                result["removed"] = result.get("removed", 0) + imported["removed"]
        if failed_courses:
            result["failed_courses"] = failed_courses
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
