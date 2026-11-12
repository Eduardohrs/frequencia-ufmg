"""Persist independent academic dates below their owning course."""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from course_repository import validate_course_id

MAX_IMPORT_DATES = 500
_SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_KINDS = {"assignment", "quiz", "event"}


class InvalidAcademicDate(Exception):
    """An academic date does not satisfy the persisted contract."""


class _Firestore(Protocol):
    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]: ...

    def patch_user_document(self, *segments: str, fields: Mapping[str, Any]) -> dict[str, Any]: ...


class AcademicDateRepository:
    def __init__(
        self,
        firestore: _Firestore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def list_dates(self, course_id: str) -> list[dict[str, Any]]:
        identifier = validate_course_id(course_id)
        dates = [
            _decode(document)
            for document in self._firestore.list_user_documents(
                "courses", identifier, "academicDates"
            )
        ]
        return sorted(dates, key=lambda item: (item["due_at"], item["id"]))

    def import_moodle_dates(
        self,
        course_id: str,
        events: list[dict[str, object]],
    ) -> dict[str, int]:
        identifier = validate_course_id(course_id)
        if len(events) > MAX_IMPORT_DATES:
            raise InvalidAcademicDate("invalid academic date batch")
        valid = [_validate_input(event) for event in events]
        if len({event["source_id"] for event in valid}) != len(valid):
            raise InvalidAcademicDate("invalid academic date batch")
        existing = {item["source_id"]: item for item in self.list_dates(identifier)}
        now = _timestamp(self._now())
        result = {"total": len(valid), "created": 0, "updated": 0, "unchanged": 0}
        for event in valid:
            previous = existing.get(event["source_id"])
            comparable = {
                "title": event["title"],
                "due_at": event["due_at"],
                "kind": event["kind"],
                "source": "moodle",
                "source_id": event["source_id"],
            }
            if previous is not None and all(
                previous[key] == value for key, value in comparable.items()
            ):
                result["unchanged"] += 1
                continue
            created_at = previous["created_at"] if previous is not None else now
            document_id = f"moodle-{event['source_id']}"
            self._firestore.patch_user_document(
                "courses",
                identifier,
                "academicDates",
                document_id,
                fields=_encode(
                    {"id": document_id, **comparable, "created_at": created_at, "updated_at": now}
                ),
            )
            result["updated" if previous is not None else "created"] += 1
        return result


def _validate_input(value: Mapping[str, object]) -> dict[str, str]:
    if set(value) != {"source_id", "title", "due_at", "kind"}:
        raise InvalidAcademicDate("invalid academic date")
    source_id = value["source_id"]
    title = value["title"]
    kind = value["kind"]
    if (
        not isinstance(source_id, str)
        or _SOURCE_ID.fullmatch(source_id) is None
        or not isinstance(title, str)
        or not title
        or title.strip() != title
        or len(title) > 120
        or not isinstance(kind, str)
        or kind not in _KINDS
    ):
        raise InvalidAcademicDate("invalid academic date")
    return {
        "source_id": source_id,
        "title": title,
        "due_at": _timestamp(_instant(value["due_at"])),
        "kind": kind,
    }


def _encode(value: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schemaVersion": {"integerValue": "1"},
        "title": {"stringValue": value["title"]},
        "dueAt": {"timestampValue": value["due_at"]},
        "kind": {"stringValue": value["kind"]},
        "source": {"stringValue": value["source"]},
        "sourceId": {"stringValue": value["source_id"]},
        "createdAt": {"timestampValue": value["created_at"]},
        "updatedAt": {"timestampValue": value["updated_at"]},
    }


def _decode(document: Mapping[str, Any]) -> dict[str, Any]:
    try:
        name = document["name"]
        fields = document["fields"]
        if not isinstance(name, str) or not isinstance(fields, Mapping):
            raise KeyError
        value = {
            "id": name.rsplit("/", 1)[-1],
            "title": fields["title"]["stringValue"],
            "due_at": fields["dueAt"]["timestampValue"],
            "kind": fields["kind"]["stringValue"],
            "source": fields["source"]["stringValue"],
            "source_id": fields["sourceId"]["stringValue"],
            "created_at": fields["createdAt"]["timestampValue"],
            "updated_at": fields["updatedAt"]["timestampValue"],
        }
        if fields["schemaVersion"] != {"integerValue": "1"}:
            raise KeyError
        valid = _validate_input(
            {key: value[key] for key in ("source_id", "title", "due_at", "kind")}
        )
        if (
            value["source"] != "moodle"
            or value["id"] != f"moodle-{valid['source_id']}"
            or _timestamp(_instant(value["created_at"])) != value["created_at"]
            or _timestamp(_instant(value["updated_at"])) != value["updated_at"]
            or _instant(value["updated_at"]) < _instant(value["created_at"])
        ):
            raise KeyError
        return value
    except (KeyError, TypeError, ValueError, InvalidAcademicDate):
        raise InvalidAcademicDate("invalid academic date") from None


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidAcademicDate("invalid academic date")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidAcademicDate("invalid academic date") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidAcademicDate("invalid academic date")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
