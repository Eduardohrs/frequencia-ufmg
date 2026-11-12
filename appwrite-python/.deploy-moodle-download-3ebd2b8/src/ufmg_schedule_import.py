"""Safely reconcile trusted SIGA timetable data with a user's local schedule."""

from collections.abc import Mapping
from typing import Any, Protocol, cast

from schedule_repository import DestructiveScheduleChange
from schedule_service import ScheduleOverlap
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession

_IMPORTED_PREFIX = "ufmg-"


class _SessionStore(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _EnrollmentClient(Protocol):
    def fetch(self, token: str) -> list[dict[str, object]]: ...


class _CourseRepository(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _ScheduleRepository(Protocol):
    def load_import_schedules(self, courses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]: ...

    def save_import_schedule(
        self,
        course_id: str,
        payload: Mapping[str, Any],
        schedules: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]: ...


class UFMGScheduleImportService:
    """Import only unambiguous timetable changes, preserving manual ownership."""

    def __init__(
        self,
        sessions: _SessionStore,
        enrollments: _EnrollmentClient,
        courses: _CourseRepository,
        schedules: _ScheduleRepository,
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._courses = courses
        self._schedules = schedules

    def import_schedules(self, user_id: str, *, now: int) -> dict[str, int]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        try:
            remote = self._enrollments.fetch(session.token)
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise

        return self.import_enrollments(remote)

    def import_enrollments(self, remote: list[dict[str, object]]) -> dict[str, int]:
        """Reconcile one already validated enrollment snapshot."""

        courses = self._courses.list_courses()
        local = {(str(course["code"]), str(course["term"])): course for course in courses}
        schedules = self._schedules.load_import_schedules(courses)
        summary = {
            "total": 0,
            "updated": 0,
            "unchanged": 0,
            "conflicts": 0,
            "missing_courses": 0,
            "meetings_imported": 0,
            "date_mismatches": 0,
            "meeting_mismatches": 0,
            "meeting_upserts": 0,
            "meeting_deletes": 0,
            "session_upserts": 0,
            "session_deletes": 0,
        }
        unique = {(str(course["code"]), str(course["term"])): course for course in remote}
        summary["total"] = len(unique)
        for key, enrollment in sorted(unique.items()):
            course = local.get(key)
            if course is None:
                summary["missing_courses"] += 1
                continue
            outcome, count, diagnostics = self._reconcile(course, enrollment, schedules)
            summary[outcome] += 1
            summary["meetings_imported"] += count
            for name, value in diagnostics.items():
                summary[name] += value
        return summary

    def _reconcile(
        self,
        course: Mapping[str, Any],
        enrollment: Mapping[str, object],
        schedules: dict[str, dict[str, Any]],
    ) -> tuple[str, int, dict[str, int]]:
        course_id = str(course["id"])
        state = schedules[course_id]
        saved_course = state["course"]
        saved_meetings = state["meetings"]
        remote_meetings = enrollment["meetings"]
        if not isinstance(saved_course, Mapping) or not isinstance(saved_meetings, list):
            raise ValueError("invalid schedule state")
        if not isinstance(remote_meetings, list):
            raise ValueError("invalid enrollment schedule")

        if any(not _is_imported(item) for item in saved_meetings):
            if _structures(saved_meetings) == _structures(remote_meetings):
                return "unchanged", 0, {}
            return "conflicts", 0, {}

        requested = _imported_meetings(remote_meetings, saved_meetings)
        starts_on, ends_on = _dates(saved_course, enrollment)
        meeting_mismatch = _requested_structures(saved_meetings) != requested
        date_mismatch = (
            saved_course.get("starts_on") != starts_on or saved_course.get("ends_on") != ends_on
        )
        diagnostics = {
            "date_mismatches": int(date_mismatch),
            "meeting_mismatches": int(meeting_mismatch),
        }
        if not meeting_mismatch and not date_mismatch:
            return "unchanged", 0, diagnostics
        try:
            saved = self._schedules.save_import_schedule(
                course_id,
                {
                    "starts_on": starts_on,
                    "ends_on": ends_on,
                    "meetings": requested,
                    "confirm_destructive": False,
                },
                schedules,
            )
        except (DestructiveScheduleChange, ScheduleOverlap):
            return "conflicts", 0, diagnostics
        schedules[course_id] = saved
        changes = saved["changes"]
        diagnostics.update(
            {
                name: int(changes[name])
                for name in (
                    "meeting_upserts",
                    "meeting_deletes",
                    "session_upserts",
                    "session_deletes",
                )
            }
        )
        return "updated", len(requested), diagnostics


def _is_imported(meeting: object) -> bool:
    if not isinstance(meeting, Mapping):
        return False
    try:
        return meeting.get("id") == _meeting_id(meeting)
    except (KeyError, TypeError, ValueError):
        return False


def _structure(meeting: Mapping[str, object]) -> tuple[int, int, int]:
    return (
        int(cast(Any, meeting["weekday"])),
        int(cast(Any, meeting["start_minutes"])),
        int(cast(Any, meeting["lesson_count"])),
    )


def _structures(meetings: list[object]) -> set[tuple[int, int, int]]:
    return {_structure(item) for item in meetings if isinstance(item, Mapping)}


def _meeting_id(meeting: Mapping[str, object]) -> str:
    weekday, start, lessons = _structure(meeting)
    return f"{_IMPORTED_PREFIX}{weekday}-{start}-{lessons}"


def _imported_meetings(remote: list[object], saved: list[object]) -> list[dict[str, object]]:
    saved_calls = {
        str(item["id"]): int(item["call_count"]) for item in saved if isinstance(item, Mapping)
    }
    result = []
    for item in remote:
        if not isinstance(item, Mapping):
            raise ValueError("invalid enrollment schedule")
        identifier = _meeting_id(item)
        result.append(
            {
                "id": identifier,
                "weekday": item["weekday"],
                "start_minutes": item["start_minutes"],
                "lesson_count": item["lesson_count"],
                "call_count": saved_calls.get(identifier, 1),
            }
        )
    return sorted(result, key=lambda item: str(item["id"]))


def _requested_structures(saved: list[object]) -> list[dict[str, object]]:
    return _imported_meetings([item for item in saved if isinstance(item, Mapping)], saved)


def _dates(course: Mapping[str, object], enrollment: Mapping[str, object]) -> tuple[object, object]:
    current = (course.get("starts_on"), course.get("ends_on"))
    if current == (None, None) or current == _default_dates(str(course["term"])):
        return enrollment["starts_on"], enrollment["ends_on"]
    return current


def _default_dates(term: str) -> tuple[str, str]:
    year, semester = term.split("-")
    if semester == "1":
        return f"{year}-01-01T00:00:00Z", f"{year}-06-30T00:00:00Z"
    return f"{year}-07-01T00:00:00Z", f"{year}-12-31T00:00:00Z"
