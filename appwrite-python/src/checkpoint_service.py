"""Validate device evidence and apply the canonical attendance policy without replacing edits."""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from attendance_service import evaluate_attendance
from schedule_service import validate_saved_session
from session_service import ATTENDANCE_CALENDAR_STATUSES, InvalidSessionMutation, _timestamp

FIELDS = {
    "starts_at_ms",
    "ends_at_ms",
    "lesson_count",
    "call_count",
    "campus_id",
    "first",
    "second",
}
REPORT_FIELDS = {"operation_id", "status", "ping", "expected_at_ms", "captured_at_ms"}
PINGS = {"no_campus", "fora", "indisponivel"}


def validate_checkpoint_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != FIELDS:
        raise InvalidSessionMutation("invalid checkpoint payload")
    for name in ("starts_at_ms", "ends_at_ms", "lesson_count", "call_count"):
        if type(payload[name]) is not int:
            raise InvalidSessionMutation("invalid checkpoint number")
    if not 0 < payload["starts_at_ms"] < payload["ends_at_ms"] < 253402300800000:
        raise InvalidSessionMutation("invalid checkpoint dates")
    if payload["lesson_count"] not in (1, 2, 4) or payload["call_count"] not in (1, 2):
        raise InvalidSessionMutation("invalid checkpoint configuration")
    if payload["lesson_count"] == 1 and payload["call_count"] == 2:
        raise InvalidSessionMutation("invalid checkpoint configuration")
    campus = payload["campus_id"]
    if not isinstance(campus, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", campus):
        raise InvalidSessionMutation("invalid checkpoint campus")
    ids = []
    for moment in ("first", "second"):
        report = payload[moment]
        if report is None:
            continue
        if not isinstance(report, dict) or set(report) != REPORT_FIELDS:
            raise InvalidSessionMutation("invalid checkpoint report")
        identifier = report["operation_id"]
        status = report["status"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier)
            or identifier in ids
        ):
            raise InvalidSessionMutation("invalid checkpoint identifier")
        ids.append(identifier)
        if (
            not isinstance(status, str)
            or not re.fullmatch(r"[a-z_]{1,64}", status)
            or status in ("scheduled", "running")
        ):
            raise InvalidSessionMutation("checkpoint is not terminal")
        if not isinstance(report["ping"], str) or report["ping"] not in PINGS:
            raise InvalidSessionMutation("invalid checkpoint ping")
        if type(report["expected_at_ms"]) is not int or (
            report["captured_at_ms"] is not None and type(report["captured_at_ms"]) is not int
        ):
            raise InvalidSessionMutation("invalid checkpoint capture time")
    return payload


def checkpoint_decision(
    session: Mapping[str, Any],
    payload: object,
    *,
    now: datetime,
) -> tuple[str, str, dict[str, Any] | None]:
    evidence = validate_checkpoint_payload(payload)
    current = validate_saved_session(session)
    start = int(
        datetime.fromisoformat(current["starts_at"].replace("Z", "+00:00")).timestamp() * 1000
    )
    end = int(datetime.fromisoformat(current["ends_at"].replace("Z", "+00:00")).timestamp() * 1000)
    if (
        start != evidence["starts_at_ms"]
        or end != evidence["ends_at_ms"]
        or current["lesson_count"] != evidence["lesson_count"]
        or current["call_count"] != evidence["call_count"]
    ):
        return "preserved", "session_changed", None
    if current["calendar_status"] not in ATTENDANCE_CALENDAR_STATUSES:
        return "preserved", "session_without_roll_call", None
    instant = int(now.timestamp() * 1000)
    pings = {}
    for moment, expected in (("first", start + 1200000), ("second", end - 1200000)):
        report = evidence[moment]
        if report is None and instant <= expected + 300000 and instant < end:
            return "waiting", "checkpoint_window_open", None
        captured = report["captured_at_ms"] if report else None
        valid = (
            report is not None
            and report["status"] == "succeeded"
            and report["expected_at_ms"] == expected
            and type(captured) is int
            and expected <= captured <= expected + 300000
            and captured < end
            and captured <= instant + 60000
        )
        pings[moment] = report["ping"] if valid else "indisponivel"
    decision = evaluate_attendance(
        {
            "lessons": current["lesson_count"],
            "calls": current["call_count"],
            "first_ping": pings["first"],
            "second_ping": pings["second"],
        }
    )
    fields = {
        "first_ping": pings["first"],
        "second_ping": pings["second"],
        "attendance_status": decision["status"],
        "absences": decision["absences"],
    }
    if all(current[key] == value for key, value in fields.items()):
        return "already_applied", "matching_evidence", None
    if any(current[key] is not None for key in ("attendance_status", "first_ping", "second_ping")):
        return "preserved", "existing_attendance", None
    if decision["status"] == "pendente":
        return "unresolved", "insufficient_evidence", None
    return (
        "applied",
        "classified",
        validate_saved_session(
            {
                **current,
                **fields,
                "updated_at": _timestamp(now),
            }
        ),
    )
