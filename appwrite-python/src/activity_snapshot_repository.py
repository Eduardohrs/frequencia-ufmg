"""Store the last complete course activity snapshot, without credentials or file bytes."""

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Protocol, cast

from course_repository import validate_course_id
from firestore_rest import FirestoreNotFound

# Leave room for Firestore's document names and the commit envelope.  A single
# snapshot is already capped at 750 KiB, so the guard below keeps normal
# courses in one request while splitting unusually large multi-course syncs.
_SAFE_COMMIT_BYTES = 900_000


class ActivitySnapshotMissing(Exception):
    """This course has never completed an activity synchronization."""


class InvalidActivitySnapshot(Exception):
    """The saved or incoming snapshot is malformed or exceeds its budget."""


class _Firestore(Protocol):
    def get_user_document(self, *segments: str) -> dict[str, Any]: ...
    def patch_user_document(self, *segments: str, fields: Mapping[str, Any]) -> dict[str, Any]: ...

    def commit_user_documents(
        self,
        *,
        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]],
        deletes: list[tuple[str, ...]],
    ) -> None: ...


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
        self.save_batch([(course_id, snapshot)])

    def save_batch(self, snapshots: list[tuple[str, dict[str, Any]]]) -> None:
        """Persist successful course snapshots in one atomic Firestore commit."""

        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
        seen: set[str] = set()
        for course_id, snapshot in snapshots:
            identifier = validate_course_id(course_id)
            if identifier in seen:
                raise InvalidActivitySnapshot("duplicate snapshot course")
            seen.add(identifier)
            encoded = _encode(snapshot)
            if snapshot["course_id"] != identifier:
                raise InvalidActivitySnapshot("snapshot course mismatch")
            updates.append(
                (
                    ("courses", identifier, "activitySnapshots", "current"),
                    {
                        "schemaVersion": {"integerValue": "1"},
                        "snapshotJson": {"stringValue": encoded},
                        "contentHash": {"stringValue": sha256(encoded.encode()).hexdigest()},
                        "updatedAt": {"timestampValue": snapshot["synced_at"]},
                    },
                )
            )
        if not updates:
            return
        commit = getattr(self._firestore, "commit_user_documents", None)
        if callable(commit):
            batch: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
            batch_bytes = 0
            for update in updates:
                update_bytes = _estimate_update_bytes(*update)
                if batch and batch_bytes + update_bytes > _SAFE_COMMIT_BYTES:
                    commit(updates=batch, deletes=[])
                    batch = []
                    batch_bytes = 0
                batch.append(update)
                batch_bytes += update_bytes
            # ``updates`` is non-empty here, so the final batch always contains
            # at least the last update after the loop.
            commit(updates=batch, deletes=[])
            return
        # Keep the repository usable with small in-memory fakes and old callers.
        for path, fields in updates:
            self._firestore.patch_user_document(*path, fields=fields)


def _estimate_update_bytes(
    path: tuple[str, ...], fields: Mapping[str, Any]
) -> int:
    """Estimate one commit write without including credentials or user data."""

    try:
        return len(
            json.dumps(
                {"update": {"name": "/".join(path), "fields": fields}},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        )
    except (TypeError, ValueError):
        raise InvalidActivitySnapshot("invalid activity snapshot") from None


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
