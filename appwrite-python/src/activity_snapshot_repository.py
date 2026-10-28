"""Store the last complete course activity snapshot, without credentials or file bytes."""

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Protocol, cast

from course_repository import validate_course_id
from firestore_rest import FirestoreNotFound


class ActivitySnapshotMissing(Exception):
    """This course has never completed an activity synchronization."""


class InvalidActivitySnapshot(Exception):
    """The saved or incoming snapshot is malformed or exceeds its budget."""


class _Firestore(Protocol):
    def get_user_document(self, *segments: str) -> dict[str, Any]: ...
    def patch_user_document(self, *segments: str, fields: Mapping[str, Any]) -> dict[str, Any]: ...


class ActivitySnapshotRepository:
    def __init__(self, firestore: _Firestore) -> None:
        self._firestore = firestore

    def load(self, course_id: str) -> dict[str, Any]:
        identifier = validate_course_id(course_id)
        try:
            document = self._firestore.get_user_document(
                "courses", identifier, "activitySnapshots", "current"
            )
        except (FirestoreNotFound, LookupError):
            raise ActivitySnapshotMissing(
                "synchronize Moodle to create an activity snapshot"
            ) from None
        try:
            fields = document["fields"]
            encoded = fields["snapshotJson"]["stringValue"]
            value = json.loads(encoded)
            if (
                fields["schemaVersion"] != {"integerValue": "1"}
                or fields["contentHash"] != {"stringValue": sha256(encoded.encode()).hexdigest()}
                or value["course_id"] != identifier
                or _encode(value) != encoded
            ):
                raise ValueError("snapshot integrity")
            return cast(dict[str, Any], value)
        except (KeyError, TypeError, ValueError):
            raise InvalidActivitySnapshot("invalid stored activity snapshot") from None

    def save(self, course_id: str, snapshot: dict[str, Any]) -> None:
        identifier = validate_course_id(course_id)
        encoded = _encode(snapshot)
        if snapshot["course_id"] != identifier:
            raise InvalidActivitySnapshot("snapshot course mismatch")
        # One document write replaces the whole course only after every activity succeeded.
        self._firestore.patch_user_document(
            "courses",
            identifier,
            "activitySnapshots",
            "current",
            fields={
                "schemaVersion": {"integerValue": "1"},
                "snapshotJson": {"stringValue": encoded},
                "contentHash": {"stringValue": sha256(encoded.encode()).hexdigest()},
                "updatedAt": {"timestampValue": snapshot["synced_at"]},
            },
        )


def _encode(value: Any) -> str:
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"course_id", "term", "synced_at", "activities"}
            or not isinstance(value["activities"], list)
            or len(value["activities"]) > 500
        ):
            raise ValueError("snapshot shape")
        for entry in value["activities"]:
            if (
                not isinstance(entry, dict)
                or entry.get("files") != []
                or not isinstance(entry.get("description"), str)
                or not isinstance(entry.get("attachments"), list)
            ):
                raise ValueError("snapshot entry")
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode()) > 750_000:
            raise ValueError("snapshot size")
        return encoded
    except (TypeError, ValueError):
        raise InvalidActivitySnapshot("invalid activity snapshot") from None
