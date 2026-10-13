"""Coordinate bounded UFMG synchronization from one enrollment snapshot."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _SessionStore(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _EnrollmentClient(Protocol):
    def fetch(self, token: str) -> list[dict[str, object]]: ...


class _Importer(Protocol):
    def import_enrollments(
        self, enrollments: list[dict[str, object]]
    ) -> dict[str, int]: ...


class UFMGSyncService:
    """Run every ready import stage without fetching the same source twice."""

    def __init__(
        self,
        sessions: _SessionStore,
        enrollments: _EnrollmentClient,
        courses: _Importer,
        schedules: _Importer,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = sessions
        self._enrollments = enrollments
        self._courses = courses
        self._schedules = schedules
        self._clock = clock or (lambda: datetime.now(UTC))

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        try:
            enrollments = self._enrollments.fetch(session.token)
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise

        checked_at = self._clock().astimezone(UTC)
        schedule_result = self._schedules.import_enrollments(enrollments)
        schedule_fields = (
            "total",
            "updated",
            "unchanged",
            "conflicts",
            "missing_courses",
            "meetings_imported",
        )
        return {
            "courses": self._courses.import_enrollments(enrollments),
            "schedules": {field: schedule_result[field] for field in schedule_fields},
            "checked_at": _timestamp(checked_at),
            "next_automatic_sync_at": _timestamp(
                _next_automatic_sync(checked_at, enrollments)
            ),
        }


def _next_automatic_sync(
    checked_at: datetime, enrollments: list[dict[str, object]]
) -> datetime:
    """Poll daily near enrollment, then sleep until the semester changes."""

    if not enrollments:
        return checked_at + timedelta(days=7)
    starts = [_date(item["starts_on"]) for item in enrollments]
    ends = [_date(item["ends_on"]) for item in enrollments]
    enrollment_window_end = min(starts) + timedelta(days=30)
    if checked_at <= enrollment_window_end:
        return checked_at + timedelta(days=1)
    semester_change = max(ends) + timedelta(days=1)
    if checked_at < semester_change:
        return semester_change
    return checked_at + timedelta(days=7)


def _date(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid enrollment date")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("invalid enrollment date")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
