"""Persist a structured Diário plan without retaining the source document."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

from course_repository import validate_course_id
from firestore_rest import FirestoreNotFound

_PLAN_KEYS = {
    "term",
    "course_code",
    "course_name",
    "class_group",
    "assessments",
    "criteria",
    "schedule",
    "source",
    "confidence",
}


class InvalidTeachingPlan(Exception):
    """A structured teaching plan does not satisfy the persisted contract."""


class _Firestore(Protocol):
    def get_user_document(self, *segments: str) -> dict[str, Any]: ...

    def patch_user_document(
        self, *segments: str, fields: Mapping[str, Any]
    ) -> dict[str, Any]: ...


class TeachingPlanRepository:
    def __init__(
        self, firestore: _Firestore, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def load(self, course_id: str) -> dict[str, object]:
        identifier = validate_course_id(course_id)
        try:
            document = self._firestore.get_user_document(
                "courses", identifier, "teachingPlans", "current"
            )
        except (FirestoreNotFound, LookupError):
            raise InvalidTeachingPlan("teaching plan not found") from None
        return _decode(document)

    def save(
        self,
        course_id: str,
        *,
        source_id: str,
        plan: Mapping[str, object],
    ) -> str:
        identifier = validate_course_id(course_id)
        canonical = _canonical(plan)
        if not source_id.isdigit() or not 1 <= int(source_id) <= 2_147_483_647:
            raise InvalidTeachingPlan("invalid teaching plan")
        digest = sha256(canonical.encode()).hexdigest()
        previous: dict[str, object] | None
        try:
            previous = self.load(identifier)
        except InvalidTeachingPlan:
            previous = None
        if (
            previous is not None
            and previous["source_id"] == source_id
            and previous["content_hash"] == digest
        ):
            return "unchanged"
        collected_at = _timestamp(self._now())
        created_at = (
            str(previous["created_at"]) if previous is not None else collected_at
        )
        fields = {
            "schemaVersion": {"integerValue": "1"},
            "source": {"stringValue": "ufmg_diario"},
            "sourceId": {"stringValue": source_id},
            "confidence": {"stringValue": "authoritative"},
            "planJson": {"stringValue": canonical},
            "contentHash": {"stringValue": digest},
            "collectedAt": {"timestampValue": collected_at},
            "createdAt": {"timestampValue": created_at},
            "updatedAt": {"timestampValue": collected_at},
        }
        self._firestore.patch_user_document(
            "courses", identifier, "teachingPlans", "current", fields=fields
        )
        return "updated" if previous is not None else "created"


def _canonical(plan: Mapping[str, object]) -> str:
    if set(plan) != _PLAN_KEYS:
        raise InvalidTeachingPlan("invalid teaching plan")
    if plan.get("source") != "ufmg_diario" or plan.get("confidence") != "authoritative":
        raise InvalidTeachingPlan("invalid teaching plan")
    try:
        encoded = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raise InvalidTeachingPlan("invalid teaching plan") from None
    if len(encoded.encode()) > 750_000:
        raise InvalidTeachingPlan("invalid teaching plan")
    return encoded


def _decode(document: Mapping[str, Any]) -> dict[str, object]:
    try:
        fields = document["fields"]
        canonical = fields["planJson"]["stringValue"]
        plan = json.loads(canonical)
        result: dict[str, object] = {
            "source_id": fields["sourceId"]["stringValue"],
            "content_hash": fields["contentHash"]["stringValue"],
            "collected_at": fields["collectedAt"]["timestampValue"],
            "created_at": fields["createdAt"]["timestampValue"],
            "updated_at": fields["updatedAt"]["timestampValue"],
            "plan": plan,
        }
        if (
            fields["schemaVersion"] != {"integerValue": "1"}
            or fields["source"] != {"stringValue": "ufmg_diario"}
            or fields["confidence"] != {"stringValue": "authoritative"}
            or not isinstance(plan, dict)
            or _canonical(plan) != canonical
            or sha256(canonical.encode()).hexdigest() != result["content_hash"]
        ):
            raise KeyError
        return result
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, InvalidTeachingPlan):
        raise InvalidTeachingPlan("invalid teaching plan") from None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTeachingPlan("invalid teaching plan")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
