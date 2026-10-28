"""Persist independent academic dates below their owning course."""

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from course_repository import validate_course_id

MAX_IMPORT_DATES = 500
_SOURCE_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_KINDS = {"assignment", "quiz", "event", "assessment"}
_SOURCES = {"moodle", "diario", "manual"}


class InvalidAcademicDate(Exception):
    """An academic date does not satisfy the persisted contract."""


class _Firestore(Protocol):
    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]: ...

    def patch_user_document(self, *segments: str, fields: Mapping[str, Any]) -> dict[str, Any]: ...

    def commit_user_documents(
        self,
        *,
        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]],
        deletes: list[tuple[str, ...]],
    ) -> None: ...


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

    def save_date(
        self, course_id: str, date_id: str, payload: Mapping[str, object]
    ) -> dict[str, Any]:
        identifier = validate_course_id(course_id)
        source, source_id = _date_identifier(date_id)
        if not isinstance(payload, Mapping) or set(payload) != {"title", "due_at", "kind"}:
            raise InvalidAcademicDate("invalid academic date mutation")
        valid = _validate_input({**payload, "source_id": source_id})
        previous = next(
            (item for item in self.list_dates(identifier) if item["id"] == date_id), None
        )
        if previous is None and source != "manual":
            raise InvalidAcademicDate("imported academic date not found")
        now = _timestamp(self._now())
        value = {
            "id": date_id,
            **valid,
            "source": source,
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
        }
        if source != "manual":
            value["manual_override"] = True
        self._firestore.patch_user_document(
            "courses", identifier, "academicDates", date_id, fields=_encode(value)
        )
        return value

    def delete_date(self, course_id: str, date_id: str) -> None:
        identifier = validate_course_id(course_id)
        source, _ = _date_identifier(date_id)
        if source != "manual":
            raise InvalidAcademicDate("only manual academic dates may be deleted manually")
        if any(item["id"] == date_id for item in self.list_dates(identifier)):
            self._firestore.commit_user_documents(
                updates=[], deletes=[("courses", identifier, "academicDates", date_id)]
            )

    def import_moodle_dates(
        self,
        course_id: str,
        events: list[dict[str, object]],
        *,
        complete: bool = False,
    ) -> dict[str, int]:
        identifier = validate_course_id(course_id)
        if len(events) > MAX_IMPORT_DATES:
            raise InvalidAcademicDate("invalid academic date batch")
        valid = [_validate_input(event) for event in events]
        if len({event["source_id"] for event in valid}) != len(valid):
            raise InvalidAcademicDate("invalid academic date batch")
        existing = {
            item["source_id"]: item
            for item in self.list_dates(identifier)
            if item["source"] == "moodle"
        }
        now = _timestamp(self._now())
        result = {"total": len(valid), "created": 0, "updated": 0, "unchanged": 0}
        pending_updates: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
        for event in valid:
            previous = existing.get(event["source_id"])
            if previous is not None and previous.get("manual_override") is True:
                result["unchanged"] += 1
                continue
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
            encoded = _encode(
                {"id": document_id, **comparable, "created_at": created_at, "updated_at": now}
            )
            segments = ("courses", identifier, "academicDates", document_id)
            if complete:
                pending_updates.append((segments, encoded))
            else:
                self._firestore.patch_user_document(*segments, fields=encoded)
            result["updated" if previous is not None else "created"] += 1
        if complete:
            current = {event["source_id"] for event in valid}
            stale = sorted(
                source_id
                for source_id in set(existing) - current
                if not existing[source_id].get("manual_override")
            )
            deletes: list[tuple[str, ...]] = [
                ("courses", identifier, "academicDates", existing[source_id]["id"])
                for source_id in stale
            ]
            if len(pending_updates) + len(deletes) > MAX_IMPORT_DATES:
                raise InvalidAcademicDate("academic date atomic batch exceeds limit")
            if pending_updates or deletes:
                self._firestore.commit_user_documents(updates=pending_updates, deletes=deletes)
            result["removed"] = len(stale)
        return result

    def import_diario_assessments(
        self,
        course_id: str,
        *,
        plan_source_id: str,
        assessments: list[dict[str, object]],
    ) -> dict[str, int]:
        identifier = validate_course_id(course_id)
        if _SOURCE_ID.fullmatch(plan_source_id) is None or len(assessments) > 100:
            raise InvalidAcademicDate("invalid academic date batch")
        events = [
            _validate_input(
                {
                    "source_id": f"{plan_source_id}-{assessment.get('code', '')}",
                    "title": assessment.get("title"),
                    "due_at": assessment.get("scheduled_at"),
                    "kind": "assessment",
                }
            )
            for assessment in assessments
        ]
        if len({event["source_id"] for event in events}) != len(events):
            raise InvalidAcademicDate("invalid academic date batch")
        existing = {
            item["source_id"]: item
            for item in self.list_dates(identifier)
            if item["source"] == "diario" and item["source_id"].startswith(f"{plan_source_id}-")
        }
        now = _timestamp(self._now())
        result = {
            "total": len(events),
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
        }
        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
        current_ids = {event["source_id"] for event in events}
        for event in events:
            previous = existing.get(event["source_id"])
            if previous is not None and previous.get("manual_override") is True:
                result["unchanged"] += 1
                continue
            comparable = {**event, "source": "diario"}
            if previous is not None and all(
                previous[key] == value for key, value in comparable.items()
            ):
                result["unchanged"] += 1
                continue
            created_at = previous["created_at"] if previous is not None else now
            document_id = f"diario-{event['source_id']}"
            updates.append(
                (
                    ("courses", identifier, "academicDates", document_id),
                    _encode(
                        {
                            "id": document_id,
                            **comparable,
                            "created_at": created_at,
                            "updated_at": now,
                        }
                    ),
                )
            )
            result["updated" if previous is not None else "created"] += 1
        stale = sorted(
            source_id
            for source_id in set(existing) - current_ids
            if not existing[source_id].get("manual_override")
        )
        deletes: list[tuple[str, ...]] = [
            ("courses", identifier, "academicDates", f"diario-{source_id}") for source_id in stale
        ]
        result["removed"] = len(deletes)
        if updates or deletes:
            self._firestore.commit_user_documents(updates=updates, deletes=deletes)
        return result


def _date_identifier(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise InvalidAcademicDate("invalid academic date identifier")
    source, separator, source_id = value.partition("-")
    if not separator or source not in _SOURCES or _SOURCE_ID.fullmatch(source_id) is None:
        raise InvalidAcademicDate("invalid academic date identifier")
    return source, source_id


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


def _encode(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": {"integerValue": "1"},
        "title": {"stringValue": value["title"]},
        "dueAt": {"timestampValue": value["due_at"]},
        "kind": {"stringValue": value["kind"]},
        "source": {"stringValue": value["source"]},
        "sourceId": {"stringValue": value["source_id"]},
        "createdAt": {"timestampValue": value["created_at"]},
        "updatedAt": {"timestampValue": value["updated_at"]},
        **(
            {"manualOverride": {"booleanValue": True}}
            if value.get("manual_override") is True
            else {}
        ),
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
            value["source"] not in _SOURCES
            or value["id"] != f"{value['source']}-{valid['source_id']}"
            or _timestamp(_instant(value["created_at"])) != value["created_at"]
            or _timestamp(_instant(value["updated_at"])) != value["updated_at"]
            or _instant(value["updated_at"]) < _instant(value["created_at"])
        ):
            raise KeyError
        if "manualOverride" in fields:
            override = fields["manualOverride"]
            if (
                not isinstance(override, Mapping)
                or set(override) != {"booleanValue"}
                or type(override["booleanValue"]) is not bool
            ):
                raise KeyError
            if override["booleanValue"]:
                value["manual_override"] = True
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
