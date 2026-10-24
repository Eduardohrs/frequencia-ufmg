"""Safe reconciliation between Diário occurrences and attendance sessions."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from schedule_service import InvalidSchedule, validate_saved_meeting, validate_saved_session

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_OCCURRENCES = 450


class InvalidTeachingPlanReconciliation(ValueError):
    """The plan or persisted sessions cannot be reconciled safely."""


@dataclass(frozen=True)
class TeachingPlanReconciliation:
    creates: tuple[dict[str, Any], ...]
    updates: tuple[dict[str, Any], ...]
    delete_ids: tuple[str, ...]
    changes: tuple[dict[str, object], ...]
    excluded: tuple[dict[str, object], ...]
    conflicts: tuple[dict[str, object], ...]
    counts: dict[str, int]


def reconcile_teaching_plan_schedule(
    schedule: object,
    existing_sessions: Iterable[Mapping[str, Any]],
    *,
    assessments: object = None,
    meetings: Iterable[Mapping[str, Any]] | None = None,
    now: datetime,
) -> TeachingPlanReconciliation:
    """Preview additive changes; exact matches remain untouched and overlaps conflict."""

    if not isinstance(schedule, list) or len(schedule) > MAX_OCCURRENCES:
        raise InvalidTeachingPlanReconciliation("invalid teaching plan schedule")
    timestamp = _utc(now)
    try:
        sessions = [validate_saved_session(item) for item in existing_sessions]
    except InvalidSchedule:
        raise InvalidTeachingPlanReconciliation("invalid saved session") from None
    try:
        weekly = None if meetings is None else [validate_saved_meeting(item) for item in meetings]
    except InvalidSchedule:
        raise InvalidTeachingPlanReconciliation("invalid saved meeting") from None
    occurrences = [_occurrence(item, timestamp) for item in schedule]
    assessment_titles = _assessment_titles(assessments or [], occurrences)
    keys = [str(item["occurrence_key"]) for item in occurrences]
    if len(set(keys)) != len(keys):
        raise InvalidTeachingPlanReconciliation("duplicate teaching plan occurrence")

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    delete_ids: list[str] = []
    conflicts: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    matched = 0
    assessments_linked = 0
    assessment_conflicts = 0
    outside_schedule = 0
    for occurrence in occurrences:
        meeting = _matching_meeting(occurrence, weekly)
        if weekly is not None and meeting is None:
            outside_schedule += 1
            exact = [
                item
                for item in sessions
                if item["starts_at"] == occurrence["starts_at"]
                and item["ends_at"] == occurrence["ends_at"]
            ]
            removable = [item for item in exact if _is_unmodified_import(item, occurrence)]
            if len(exact) == 1 and removable:
                delete_ids.append(str(removable[0]["id"]))
                changes.append(_change(occurrence, action="remove_session"))
                continue
            excluded.append({
                **_change(occurrence, action="excluded"),
                "reason": "outside_weekly_schedule",
            })
            continue
        title = assessment_titles.get(str(occurrence["occurrence_key"]))
        exact = [
            item
            for item in sessions
            if item["starts_at"] == occurrence["starts_at"]
            and item["ends_at"] == occurrence["ends_at"]
        ]
        if exact:
            matched += 1
            if title is not None and len(exact) == 1:
                saved_title = exact[0]["assessment_title"]
                if saved_title is None:
                    updates.append(
                        {
                            **exact[0],
                            "assessment_title": title,
                            "updated_at": _format(timestamp),
                        }
                    )
                    assessments_linked += 1
                    changes.append(_change(occurrence, action="link_assessment"))
                elif saved_title != title:
                    conflicts.append({
                        "occurrence_key": occurrence["occurrence_key"],
                        "reason": "assessment_title_mismatch",
                        "existing_session_ids": [str(exact[0]["id"])],
                    })
                    assessment_conflicts += 1
            continue
        overlaps = [item for item in sessions if _overlaps(item, occurrence)]
        if overlaps:
            conflicts.append(
                {
                    "occurrence_key": occurrence["occurrence_key"],
                    "reason": "overlapping_session",
                    "existing_session_ids": sorted(str(item["id"]) for item in overlaps),
                }
            )
            continue
        creates.append(
            _new_session(
                occurrence,
                timestamp,
                assessment_title=title,
                call_count=1 if meeting is None else int(meeting["call_count"]),
            )
        )
        changes.append(_change(occurrence, action="create_session"))
        assessments_linked += int(title is not None)
    return TeachingPlanReconciliation(
        creates=tuple(creates),
        updates=tuple(updates),
        delete_ids=tuple(delete_ids),
        changes=tuple(changes),
        excluded=tuple(excluded),
        conflicts=tuple(conflicts),
        counts={
            "matched": matched,
            "missing": len(creates),
            "conflicting": len(conflicts),
            "assessments_linked": assessments_linked,
            "assessment_conflicts": assessment_conflicts,
            "outside_schedule": outside_schedule,
        },
    )


def _occurrence(value: object, now: datetime) -> dict[str, object]:
    required = {
        "sequence",
        "occurrence_key",
        "date",
        "weekday",
        "lesson_count",
        "starts_at",
        "ends_at",
        "kind",
        "subject",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise InvalidTeachingPlanReconciliation("invalid teaching plan occurrence")
    try:
        day = date.fromisoformat(str(value["date"]))
        start_clock = time.fromisoformat(str(value["starts_at"]))
        end_clock = time.fromisoformat(str(value["ends_at"]))
        lessons = value["lesson_count"]
        if type(lessons) is not int or lessons not in {1, 2, 4}:
            raise ValueError
        local_start = datetime.combine(day, start_clock, SAO_PAULO)
        local_end = datetime.combine(day, end_clock, SAO_PAULO)
        if local_end - local_start != timedelta(minutes=lessons * 50):
            raise ValueError
        key = f"{day.isoformat()}T{start_clock.strftime('%H:%M')}-{end_clock.strftime('%H:%M')}"
        if value["occurrence_key"] != key or day.year < 2020 or day.year > now.year + 2:
            raise ValueError
    except (TypeError, ValueError):
        raise InvalidTeachingPlanReconciliation("invalid teaching plan occurrence") from None
    return {
        "occurrence_key": key,
        "date": day.isoformat(),
        "local_starts_at": start_clock.strftime("%H:%M"),
        "local_ends_at": end_clock.strftime("%H:%M"),
        "subject": str(value["subject"]),
        "starts_at": _format(local_start.astimezone(UTC)),
        "ends_at": _format(local_end.astimezone(UTC)),
        "lesson_count": lessons,
    }


def _new_session(
    occurrence: Mapping[str, object],
    now: datetime,
    *,
    assessment_title: str | None = None,
    call_count: int = 1,
) -> dict[str, Any]:
    day, interval = str(occurrence["occurrence_key"]).split("T", 1)
    start, end = interval.split("-", 1)
    return {
        "id": f"{day}--diario-{start.replace(':', '')}-{end.replace(':', '')}",
        "starts_at": occurrence["starts_at"],
        "ends_at": occurrence["ends_at"],
        "lesson_count": occurrence["lesson_count"],
        "call_count": call_count,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": None,
        "absences": None,
        "calendar_status": "scheduled",
        "assessment_title": assessment_title,
        "created_at": _format(now),
        "updated_at": _format(now),
    }


def _matching_meeting(
    occurrence: Mapping[str, object],
    meetings: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if meetings is None:
        return None
    day = date.fromisoformat(str(occurrence["date"]))
    start = time.fromisoformat(str(occurrence["local_starts_at"]))
    start_minutes = start.hour * 60 + start.minute
    for meeting in meetings:
        if (
            meeting["weekday"] == day.isoweekday()
            and meeting["start_minutes"] == start_minutes
            and meeting["lesson_count"] == occurrence["lesson_count"]
        ):
            return meeting
    return None


def _change(occurrence: Mapping[str, object], *, action: str) -> dict[str, object]:
    return {
        "action": action,
        "occurrence_key": occurrence["occurrence_key"],
        "date": occurrence["date"],
        "starts_at": occurrence["local_starts_at"],
        "ends_at": occurrence["local_ends_at"],
        "subject": occurrence["subject"],
    }


def _is_unmodified_import(
    session: Mapping[str, object], occurrence: Mapping[str, object]
) -> bool:
    day, interval = str(occurrence["occurrence_key"]).split("T", 1)
    start, end = interval.split("-", 1)
    expected_id = f"{day}--diario-{start.replace(':', '')}-{end.replace(':', '')}"
    return (
        session["id"] == expected_id
        and session["attendance_status"] is None
        and session["first_ping"] is None
        and session["second_ping"] is None
        and session["calendar_status"] == "scheduled"
        and session["assessment_title"] is None
    )


def _assessment_titles(
    assessments: object, occurrences: list[dict[str, object]]
) -> dict[str, str]:
    if not isinstance(assessments, list) or len(assessments) > 100:
        raise InvalidTeachingPlanReconciliation("invalid teaching plan assessments")
    matches: dict[str, list[str]] = {}
    for assessment in assessments:
        if not isinstance(assessment, Mapping):
            raise InvalidTeachingPlanReconciliation("invalid teaching plan assessment")
        title = assessment.get("title")
        scheduled_at = assessment.get("scheduled_at")
        if (
            not isinstance(title, str)
            or not title
            or len(title) > 120
            or not isinstance(scheduled_at, str)
        ):
            raise InvalidTeachingPlanReconciliation("invalid teaching plan assessment")
        try:
            instant = datetime.fromisoformat(scheduled_at).astimezone(UTC)
        except ValueError:
            raise InvalidTeachingPlanReconciliation("invalid teaching plan assessment") from None
        for occurrence in occurrences:
            if _parse_utc(occurrence["starts_at"]) <= instant <= _parse_utc(occurrence["ends_at"]):
                matches.setdefault(str(occurrence["occurrence_key"]), []).append(title)
    return {key: titles[0] for key, titles in matches.items() if len(titles) == 1}


def _parse_utc(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _overlaps(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return str(left["starts_at"]) < str(right["ends_at"]) and str(right["starts_at"]) < str(
        left["ends_at"]
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTeachingPlanReconciliation("invalid clock")
    return value.astimezone(UTC)


def _format(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
