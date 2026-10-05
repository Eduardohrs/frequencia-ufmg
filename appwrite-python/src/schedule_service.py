"""Authoritative validation and reconciliation for course schedules."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from course_service import InvalidCourse, validate_course

MEETING_INPUT_FIELDS = {
    "id",
    "weekday",
    "start_minutes",
    "lesson_count",
    "call_count",
}
MEETING_FIELDS = MEETING_INPUT_FIELDS | {"end_minutes", "created_at", "updated_at"}
SESSION_FIELDS = {
    "id",
    "starts_at",
    "ends_at",
    "lesson_count",
    "call_count",
    "first_ping",
    "second_ping",
    "attendance_status",
    "absences",
    "calendar_status",
    "assessment_title",
    "created_at",
    "updated_at",
}
LESSON_COUNTS = {1, 2, 4}
CALL_COUNTS = {1, 2}
PING_STATES = {"no_campus", "fora", "indisponivel"}
ATTENDANCE_STATES = {
    "presente",
    "chegou_atrasado",
    "saiu_mais_cedo",
    "ausente",
    "pendente",
}
CALENDAR_STATES = {"scheduled", "cancelled", "holiday", "no_call", "makeup"}
GENERATED_ID = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}--.+$")
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_MEETINGS = 32
MAX_GENERATED_SESSIONS = 450


class InvalidSchedule(Exception):
    """The requested schedule cannot satisfy the domain contract."""


class ScheduleOverlap(InvalidSchedule):
    """At least two active weekly meetings intersect."""


@dataclass(frozen=True)
class SchedulePlan:
    """Validated state plus the minimal Firestore changes required to reach it."""

    course: dict[str, Any]
    meetings: tuple[dict[str, Any], ...]
    meeting_upserts: tuple[dict[str, Any], ...]
    meeting_delete_ids: tuple[str, ...]
    session_upserts: tuple[dict[str, Any], ...]
    session_delete_ids: tuple[str, ...]
    destructive_delete_count: int


def build_schedule_plan(
    *,
    course: Mapping[str, Any],
    requested_starts_on: object,
    requested_ends_on: object,
    requested_meetings: object,
    existing_meetings: Iterable[Mapping[str, Any]],
    existing_sessions: Iterable[Mapping[str, Any]],
    other_schedules: Iterable[tuple[Mapping[str, Any], Iterable[Mapping[str, Any]]]],
    now: datetime,
) -> SchedulePlan:
    """Validate a complete schedule replacement and calculate an idempotent plan."""

    timestamp = _aware_utc(now)
    try:
        current_course = validate_course(course)
    except InvalidCourse:
        raise InvalidSchedule("invalid schedule") from None
    _require_mutable_term(str(current_course["term"]), timestamp.date())
    starts_on, ends_on = _period(
        str(current_course["term"]), requested_starts_on, requested_ends_on
    )

    saved_meetings = _unique_records(existing_meetings, validate_saved_meeting)
    meetings = _requested_meetings(requested_meetings, saved_meetings, timestamp)
    if meetings and starts_on is None:
        raise InvalidSchedule("invalid schedule")
    _reject_internal_overlap(meetings)
    _reject_external_overlap(
        starts_on,
        ends_on,
        meetings,
        other_schedules,
    )

    saved_sessions = _unique_records(existing_sessions, validate_saved_session)
    desired = _desired_sessions(meetings, starts_on, ends_on, timestamp)
    session_upserts, session_delete_ids, destructive_count = _reconcile_sessions(
        desired, saved_sessions, timestamp
    )

    saved_by_id = {str(item["id"]): item for item in saved_meetings}
    requested_by_id = {str(item["id"]): item for item in meetings}
    meeting_upserts = tuple(item for item in meetings if saved_by_id.get(str(item["id"])) != item)
    meeting_delete_ids = tuple(sorted(set(saved_by_id) - set(requested_by_id)))
    changed_period = current_course["starts_on"] != _format_optional(starts_on) or current_course[
        "ends_on"
    ] != _format_optional(ends_on)
    updated_course = {
        **current_course,
        "starts_on": _format_optional(starts_on),
        "ends_on": _format_optional(ends_on),
        "updated_at": _format_instant(timestamp)
        if changed_period
        else current_course["updated_at"],
    }
    return SchedulePlan(
        course=updated_course,
        meetings=tuple(meetings),
        meeting_upserts=meeting_upserts,
        meeting_delete_ids=meeting_delete_ids,
        session_upserts=session_upserts,
        session_delete_ids=session_delete_ids,
        destructive_delete_count=destructive_count,
    )


def validate_saved_meeting(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete meeting representation used by Firestore and the API."""

    if set(payload) != MEETING_FIELDS:
        raise InvalidSchedule("invalid schedule")
    meeting_id = _identifier(payload["id"])
    weekday = _integer(payload["weekday"], minimum=1, maximum=7)
    start_minutes = _integer(payload["start_minutes"], minimum=0, maximum=1439)
    lesson_count = _lesson_count(payload["lesson_count"])
    call_count = _call_count(payload["call_count"], lesson_count)
    end_minutes = _integer(payload["end_minutes"], minimum=1, maximum=1440)
    if end_minutes != start_minutes + lesson_count * 50:
        raise InvalidSchedule("invalid schedule")
    created_at = _instant(payload["created_at"])
    updated_at = _instant(payload["updated_at"])
    if updated_at < created_at:
        raise InvalidSchedule("invalid schedule")
    return {
        "id": meeting_id,
        "weekday": weekday,
        "start_minutes": start_minutes,
        "end_minutes": end_minutes,
        "lesson_count": lesson_count,
        "call_count": call_count,
        "created_at": _format_instant(created_at),
        "updated_at": _format_instant(updated_at),
    }


def validate_saved_session(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the complete session representation without changing user evidence."""

    if set(payload) != SESSION_FIELDS:
        raise InvalidSchedule("invalid schedule")
    session_id = _identifier(payload["id"])
    starts_at = _instant(payload["starts_at"])
    ends_at = _instant(payload["ends_at"])
    lesson_count = _lesson_count(payload["lesson_count"])
    call_count = _call_count(payload["call_count"], lesson_count)
    if ends_at <= starts_at:
        raise InvalidSchedule("invalid schedule")
    first_ping = _nullable_enum(payload["first_ping"], PING_STATES)
    second_ping = _nullable_enum(payload["second_ping"], PING_STATES)
    attendance = _nullable_enum(payload["attendance_status"], ATTENDANCE_STATES)
    absences = payload["absences"]
    unresolved = attendance in {None, "pendente"}
    if unresolved:
        if absences is not None:
            raise InvalidSchedule("invalid schedule")
    elif type(absences) is not int or not 0 <= absences <= lesson_count:
        raise InvalidSchedule("invalid schedule")
    calendar = _required_enum(payload["calendar_status"], CALENDAR_STATES)
    assessment = _nullable_text(payload["assessment_title"], 120)
    created_at = _instant(payload["created_at"])
    updated_at = _instant(payload["updated_at"])
    if updated_at < created_at:
        raise InvalidSchedule("invalid schedule")
    return {
        "id": session_id,
        "starts_at": _format_instant(starts_at),
        "ends_at": _format_instant(ends_at),
        "lesson_count": lesson_count,
        "call_count": call_count,
        "first_ping": first_ping,
        "second_ping": second_ping,
        "attendance_status": attendance,
        "absences": absences,
        "calendar_status": calendar,
        "assessment_title": assessment,
        "created_at": _format_instant(created_at),
        "updated_at": _format_instant(updated_at),
    }


def _requested_meetings(
    value: object,
    existing: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_MEETINGS:
        raise InvalidSchedule("invalid schedule")
    existing_by_id = {str(item["id"]): item for item in existing}
    meetings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != MEETING_INPUT_FIELDS:
            raise InvalidSchedule("invalid schedule")
        meeting_id = _identifier(raw["id"])
        if meeting_id in seen:
            raise InvalidSchedule("invalid schedule")
        seen.add(meeting_id)
        weekday = _integer(raw["weekday"], minimum=1, maximum=7)
        start_minutes = _integer(raw["start_minutes"], minimum=0, maximum=1439)
        lesson_count = _lesson_count(raw["lesson_count"])
        call_count = _call_count(raw["call_count"], lesson_count)
        end_minutes = start_minutes + lesson_count * 50
        if end_minutes > 1440:
            raise InvalidSchedule("invalid schedule")
        existing_item = existing_by_id.get(meeting_id)
        structure = {
            "id": meeting_id,
            "weekday": weekday,
            "start_minutes": start_minutes,
            "end_minutes": end_minutes,
            "lesson_count": lesson_count,
            "call_count": call_count,
        }
        unchanged = existing_item is not None and all(
            existing_item[key] == structure[key] for key in structure
        )
        created_at = (
            existing_item["created_at"] if existing_item is not None else _format_instant(now)
        )
        updated_at = (
            existing_item["updated_at"]
            if existing_item is not None and unchanged
            else _format_instant(now)
        )
        meetings.append(
            {
                **structure,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    return sorted(
        meetings,
        key=lambda item: (item["weekday"], item["start_minutes"], item["id"]),
    )


def _reject_internal_overlap(meetings: list[dict[str, Any]]) -> None:
    for index, meeting in enumerate(meetings):
        if any(_meetings_overlap(meeting, other) for other in meetings[index + 1 :]):
            raise ScheduleOverlap("schedule overlap")


def _reject_external_overlap(
    starts_on: datetime | None,
    ends_on: datetime | None,
    meetings: list[dict[str, Any]],
    other_schedules: Iterable[tuple[Mapping[str, Any], Iterable[Mapping[str, Any]]]],
) -> None:
    if not meetings or starts_on is None or ends_on is None:
        return
    for raw_course, raw_meetings in other_schedules:
        try:
            other = validate_course(raw_course)
        except InvalidCourse:
            raise InvalidSchedule("invalid schedule") from None
        other_start, other_end = _effective_course_period(other)
        if starts_on.date() > other_end or other_start > ends_on.date():
            continue
        for other_meeting in _unique_records(raw_meetings, validate_saved_meeting):
            if any(_meetings_overlap(meeting, other_meeting) for meeting in meetings):
                raise ScheduleOverlap("schedule overlap")


def _desired_sessions(
    meetings: list[dict[str, Any]],
    starts_on: datetime | None,
    ends_on: datetime | None,
    now: datetime,
) -> list[dict[str, Any]]:
    if starts_on is None or ends_on is None:
        return []
    desired: list[dict[str, Any]] = []
    day = starts_on.date()
    last_day = ends_on.date()
    while day <= last_day:
        for meeting in meetings:
            if day.isoweekday() != meeting["weekday"]:
                continue
            local_start = datetime.combine(
                day,
                time(
                    hour=int(meeting["start_minutes"]) // 60,
                    minute=int(meeting["start_minutes"]) % 60,
                    tzinfo=SAO_PAULO,
                ),
            )
            starts_at = local_start.astimezone(UTC)
            ends_at = starts_at + timedelta(
                minutes=int(meeting["end_minutes"]) - int(meeting["start_minutes"])
            )
            desired.append(
                {
                    "id": f"{day.isoformat()}--{meeting['id']}",
                    "starts_at": _format_instant(starts_at),
                    "ends_at": _format_instant(ends_at),
                    "lesson_count": meeting["lesson_count"],
                    "call_count": meeting["call_count"],
                    "first_ping": None,
                    "second_ping": None,
                    "attendance_status": None,
                    "absences": None,
                    "calendar_status": "scheduled",
                    "assessment_title": None,
                    "created_at": _format_instant(now),
                    "updated_at": _format_instant(now),
                }
            )
            if len(desired) > MAX_GENERATED_SESSIONS:
                raise InvalidSchedule("invalid schedule")
        day += timedelta(days=1)
    return sorted(desired, key=lambda item: (item["starts_at"], item["id"]))


def _reconcile_sessions(
    desired: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    now: datetime,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...], int]:
    existing_by_id = {str(item["id"]): item for item in existing}
    desired_ids = {str(item["id"]) for item in desired}
    upserts: list[dict[str, Any]] = []
    for generated in desired:
        saved = existing_by_id.get(str(generated["id"]))
        if saved is None:
            upserts.append(generated)
            continue
        if _same_session_schedule(saved, generated) or _has_attendance_evidence(saved):
            continue
        upserts.append(
            {
                **generated,
                "calendar_status": saved["calendar_status"],
                "assessment_title": saved["assessment_title"],
                "created_at": saved["created_at"],
                "updated_at": _format_instant(now),
            }
        )
    obsolete = sorted(
        (
            item
            for item in existing
            if GENERATED_ID.fullmatch(str(item["id"])) is not None and item["id"] not in desired_ids
        ),
        key=lambda item: str(item["id"]),
    )
    return (
        tuple(upserts),
        tuple(str(item["id"]) for item in obsolete),
        sum(1 for item in obsolete if _is_protected(item)),
    )


def _same_session_schedule(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(
        left[key] == right[key] for key in ("starts_at", "ends_at", "lesson_count", "call_count")
    )


def _has_attendance_evidence(session: Mapping[str, Any]) -> bool:
    return any(
        session[field] is not None
        for field in ("first_ping", "second_ping", "attendance_status", "absences")
    )


def _is_protected(session: Mapping[str, Any]) -> bool:
    return (
        _has_attendance_evidence(session)
        or session["calendar_status"] != "scheduled"
        or session["assessment_title"] is not None
    )


def _period(
    term: str,
    raw_start: object,
    raw_end: object,
) -> tuple[datetime | None, datetime | None]:
    if raw_start is None and raw_end is None:
        return None, None
    if raw_start is None or raw_end is None:
        raise InvalidSchedule("invalid schedule")
    starts_on = _instant(raw_start)
    ends_on = _instant(raw_end)
    if starts_on.time() != time(0) or ends_on.time() != time(0):
        raise InvalidSchedule("invalid schedule")
    term_start, term_end = _term_dates(term)
    if starts_on > ends_on or starts_on.date() < term_start or ends_on.date() > term_end:
        raise InvalidSchedule("invalid schedule")
    return starts_on, ends_on


def _effective_course_period(course: Mapping[str, Any]) -> tuple[date, date]:
    starts_on = course["starts_on"]
    ends_on = course["ends_on"]
    if starts_on is None or ends_on is None:
        return _term_dates(str(course["term"]))
    return _instant(starts_on).date(), _instant(ends_on).date()


def _term_dates(term: str) -> tuple[date, date]:
    try:
        year_text, semester_text = term.split("-")
        year = int(year_text)
        semester = int(semester_text)
    except (AttributeError, TypeError, ValueError):
        raise InvalidSchedule("invalid schedule") from None
    if semester == 1:
        return date(year, 1, 1), date(year, 6, 30)
    if semester == 2:
        return date(year, 7, 1), date(year, 12, 31)
    raise InvalidSchedule("invalid schedule")


def _require_mutable_term(term: str, today: date) -> None:
    current = f"{today.year}-{1 if today.month <= 6 else 2}"
    current_year, current_semester = (int(part) for part in current.split("-"))
    following = f"{current_year}-2" if current_semester == 1 else f"{current_year + 1}-1"
    if term not in {current, following}:
        raise InvalidSchedule("invalid schedule")


def _meetings_overlap(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        left["weekday"] == right["weekday"]
        and int(left["start_minutes"]) < int(right["end_minutes"])
        and int(right["start_minutes"]) < int(left["end_minutes"])
    )


def _unique_records(
    values: Iterable[Mapping[str, Any]],
    validator: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        valid = validator(value)
        identifier = str(valid["id"])
        if identifier in seen:
            raise InvalidSchedule("invalid schedule")
        seen.add(identifier)
        result.append(valid)
    return result


def _identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value.strip() != value
        or "/" in value
        or "\\" in value
    ):
        raise InvalidSchedule("invalid schedule")
    return value


def _integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidSchedule("invalid schedule")
    return value


def _lesson_count(value: object) -> int:
    if type(value) is not int or value not in LESSON_COUNTS:
        raise InvalidSchedule("invalid schedule")
    return value


def _call_count(value: object, lesson_count: int) -> int:
    if type(value) is not int or value not in CALL_COUNTS or (lesson_count == 1 and value == 2):
        raise InvalidSchedule("invalid schedule")
    return value


def _nullable_enum(value: object, allowed: set[str]) -> str | None:
    if value is None:
        return None
    return _required_enum(value, allowed)


def _required_enum(value: object, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidSchedule("invalid schedule")
    return value


def _nullable_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum:
        raise InvalidSchedule("invalid schedule")
    return value


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidSchedule("invalid schedule")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidSchedule("invalid schedule") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidSchedule("invalid schedule")
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidSchedule("invalid schedule")
    return value.astimezone(UTC)


def _format_optional(value: datetime | None) -> str | None:
    return None if value is None else _format_instant(value)


def _format_instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
