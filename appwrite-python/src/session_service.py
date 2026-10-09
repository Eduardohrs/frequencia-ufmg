"""Authoritative, bounded mutations for one persisted academic session."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from attendance_service import evaluate_attendance
from schedule_service import validate_saved_session

ATTENDANCE_STATUSES = {
    "presente",
    "chegou_atrasado",
    "saiu_mais_cedo",
    "ausente",
    "pendente",
}
ATTENDANCE_CALENDAR_STATUSES = {"scheduled", "makeup"}
EDITABLE_CALENDAR_STATUSES = {"scheduled", "cancelled", "holiday", "no_call"}


class InvalidSessionMutation(ValueError):
    """A public mutation does not satisfy the session contract."""


class InactiveAttendanceSession(InvalidSessionMutation):
    """Attendance cannot be recorded for a session without a roll call."""


def replace_attendance(
    session: Mapping[str, Any],
    payload: object,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Replace attendance, calculating defaults only when absences are omitted."""

    current = validate_saved_session(session)
    if current["calendar_status"] not in ATTENDANCE_CALENDAR_STATUSES:
        raise InactiveAttendanceSession("session does not require attendance")
    if not isinstance(payload, Mapping) or set(payload) not in (
        {"status"},
        {"status", "absences"},
    ):
        raise InvalidSessionMutation("invalid attendance mutation")
    status = payload["status"]
    if not isinstance(status, str) or status not in ATTENDANCE_STATUSES:
        raise InvalidSessionMutation("invalid attendance mutation")

    if "absences" not in payload:
        decision = evaluate_attendance(
            {
                "lessons": current["lesson_count"],
                "calls": current["call_count"],
                "status": status,
            }
        )
        absences = decision["absences"]
    else:
        absences = payload["absences"]
        unresolved = status == "pendente"
        if unresolved != (absences is None):
            raise InvalidSessionMutation("invalid attendance mutation")
        if not unresolved and (
            type(absences) is not int or not 0 <= absences <= current["lesson_count"]
        ):
            raise InvalidSessionMutation("invalid attendance mutation")

    return validate_saved_session(
        {
            **current,
            "attendance_status": status,
            "absences": absences,
            "updated_at": _timestamp(now),
        }
    )


def replace_calendar_status(
    session: Mapping[str, Any],
    payload: object,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Replace only the academic status, preserving attendance evidence."""

    current = validate_saved_session(session)
    if not isinstance(payload, Mapping) or set(payload) != {"calendar_status"}:
        raise InvalidSessionMutation("invalid calendar mutation")
    status = payload["calendar_status"]
    if not isinstance(status, str) or status not in EDITABLE_CALENDAR_STATUSES:
        raise InvalidSessionMutation("invalid calendar mutation")
    return validate_saved_session(
        {
            **current,
            "calendar_status": status,
            "updated_at": _timestamp(now),
        }
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidSessionMutation("invalid mutation time")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
