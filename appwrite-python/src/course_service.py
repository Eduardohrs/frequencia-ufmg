"""Validate course API payloads and translate the existing Firestore schema."""

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

COURSE_FIELDS = {
    "id",
    "code",
    "name",
    "workload",
    "term",
    "starts_on",
    "ends_on",
    "created_at",
    "updated_at",
}


class InvalidCourse(Exception):
    """A course does not satisfy the public API and Firestore contract."""


def validate_course(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical course or reject the entire payload."""

    if set(payload) != COURSE_FIELDS:
        raise InvalidCourse("invalid course")
    course_id = _text(payload["id"], 128)
    if "/" in course_id or "\\" in course_id:
        raise InvalidCourse("invalid course")
    code = _text(payload["code"], 32)
    name = _text(payload["name"], 160)
    workload = payload["workload"]
    term = payload["term"]
    if code != code.upper() or type(workload) is not int or workload <= 0:
        raise InvalidCourse("invalid course")
    if not isinstance(term, str) or re.fullmatch(r"[0-9]{4}-[12]", term) is None:
        raise InvalidCourse("invalid course")
    starts_on = _nullable_instant(payload["starts_on"])
    ends_on = _nullable_instant(payload["ends_on"])
    if (starts_on is None) != (ends_on is None):
        raise InvalidCourse("invalid course")
    if starts_on is not None and ends_on is not None and starts_on > ends_on:
        raise InvalidCourse("invalid course")
    created_at = _instant(payload["created_at"])
    updated_at = _instant(payload["updated_at"])
    if updated_at < created_at:
        raise InvalidCourse("invalid course")
    return {
        "id": course_id,
        "code": code,
        "name": name,
        "workload": workload,
        "term": term,
        "starts_on": _format_instant(starts_on),
        "ends_on": _format_instant(ends_on),
        "created_at": _format_instant(created_at),
        "updated_at": _format_instant(updated_at),
    }


def course_to_firestore(course: Mapping[str, Any]) -> dict[str, Any]:
    """Encode a validated course as Firestore REST typed fields."""

    valid = validate_course(course)
    return {
        "schemaVersion": {"integerValue": "1"},
        "code": {"stringValue": valid["code"]},
        "name": {"stringValue": valid["name"]},
        "workload": {"integerValue": str(valid["workload"])},
        "term": {"stringValue": valid["term"]},
        "startsOn": _firestore_instant(valid["starts_on"]),
        "endsOn": _firestore_instant(valid["ends_on"]),
        "createdAt": {"timestampValue": valid["created_at"]},
        "updatedAt": {"timestampValue": valid["updated_at"]},
    }


def course_from_firestore(course_id: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Decode only the exact version-one course schema."""

    try:
        if fields["schemaVersion"] != {"integerValue": "1"}:
            raise KeyError
        payload = {
            "id": course_id,
            "code": fields["code"]["stringValue"],
            "name": fields["name"]["stringValue"],
            "workload": int(fields["workload"]["integerValue"]),
            "term": fields["term"]["stringValue"],
            "starts_on": _read_firestore_instant(fields["startsOn"]),
            "ends_on": _read_firestore_instant(fields["endsOn"]),
            "created_at": fields["createdAt"]["timestampValue"],
            "updated_at": fields["updatedAt"]["timestampValue"],
        }
    except (KeyError, TypeError, ValueError):
        raise InvalidCourse("invalid course") from None
    return validate_course(payload)


def _text(value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or len(value) > maximum:
        raise InvalidCourse("invalid course")
    return value


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidCourse("invalid course")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidCourse("invalid course") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidCourse("invalid course")
    return parsed.astimezone(UTC)


def _nullable_instant(value: object) -> datetime | None:
    return None if value is None else _instant(value)


def _format_instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _firestore_instant(value: object) -> dict[str, Any]:
    return {"nullValue": None} if value is None else {"timestampValue": value}


def _read_firestore_instant(value: object) -> object:
    if value == {"nullValue": None}:
        return None
    if isinstance(value, Mapping) and set(value) == {"timestampValue"}:
        return value["timestampValue"]
    raise InvalidCourse("invalid course")
