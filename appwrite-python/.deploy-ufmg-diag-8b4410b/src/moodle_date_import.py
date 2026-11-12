"""Match Moodle's structured calendar events to local UFMG courses."""

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Protocol

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
        self, course_id: str, events: list[dict[str, object]]
    ) -> dict[str, int]: ...


class MoodleDateImportService:
    def __init__(
        self,
        sessions: _Sessions,
        client: _Client,
        courses: _Courses,
        dates: _Dates,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._courses = courses
        self._dates = dates

    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        courses = self._courses.list_courses()
        try:
            events: list[dict[str, str]] = []
            course_groups = _courses_by_term(courses)
            for term in sorted(course_groups):
                events.extend(
                    self._client.fetch(
                        session.token,
                        term=term,
                        months=_months(course_groups[term]),
                    )
                )
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise

        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        unmatched = 0
        for event in events:
            matches = [course for course in courses if _matches(event, course)]
            if len(matches) != 1:
                unmatched += 1
                continue
            grouped[matches[0]["id"]].append(
                {key: event[key] for key in ("source_id", "title", "due_at", "kind")}
            )

        result = {
            "total": len(events),
            "matched": len(events) - unmatched,
            "unmatched": unmatched,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
        }
        for course_id in sorted(grouped):
            imported = self._dates.import_moodle_dates(course_id, grouped[course_id])
            for field in ("created", "updated", "unchanged"):
                result[field] += imported[field]
        return result


def _matches(event: dict[str, str], course: dict[str, Any]) -> bool:
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


def _months(courses: list[dict[str, Any]]) -> list[tuple[int, int]]:
    values: set[tuple[int, int]] = set()
    for course in courses:
        starts_on = course.get("starts_on")
        ends_on = course.get("ends_on")
        if isinstance(starts_on, str) and isinstance(ends_on, str):
            start = _instant(starts_on)
            end = _instant(ends_on)
            cursor = datetime(start.year, start.month, 1)
            finish = datetime(end.year, end.month, 1)
            while cursor <= finish:
                values.add((cursor.year, cursor.month))
                cursor = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
        else:
            term = course.get("term")
            if not isinstance(term, str) or re.fullmatch(r"[0-9]{4}-[12]", term) is None:
                raise ValueError("invalid course term")
            year = int(term[:4])
            values.update(
                (year, month) for month in (range(1, 7) if term[-1] == "1" else range(7, 13))
            )
    months = sorted(values)
    if not months or len(months) > 12:
        raise ValueError("invalid Moodle month range")
    return months


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("invalid course date")
    return parsed
