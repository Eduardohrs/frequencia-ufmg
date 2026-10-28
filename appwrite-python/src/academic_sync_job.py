"""Durable sync lifecycle; a short HTTP request only dispatches an encrypted worker."""

import json
import re
from base64 import b64decode, b64encode
from collections.abc import Callable, Mapping
from os import urandom
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from firestore_rest import FirestoreConflict, FirestoreNotFound, FirestoreRestClient
from sync_timing import _emit as emit_telemetry

LEASE_SECONDS = 1800


class InvalidJob(ValueError):
    """Untrusted, malformed or expired worker envelope."""


class JobCipher:
    def __init__(self, keys: dict[int, bytes], active: int) -> None:
        self.keys, self.active = keys, active

    def seal(self, uid: str, operation: str, token: str, *, now: int) -> dict[str, object]:
        nonce = urandom(12)
        data = json.dumps([uid, operation, token, now]).encode()
        return {
            "version": self.active,
            "nonce": b64encode(nonce).decode(),
            "ciphertext": b64encode(
                AESGCM(self.keys[self.active]).encrypt(nonce, data, b"academic-sync-job-v1")
            ).decode(),
        }

    def open(self, value: Any, *, now: int) -> tuple[str, str, str]:
        try:
            if not isinstance(value, dict) or set(value) != {"version", "nonce", "ciphertext"}:
                raise ValueError()
            uid, operation, token, issued = json.loads(
                AESGCM(self.keys[value["version"]]).decrypt(
                    b64decode(value["nonce"], validate=True),
                    b64decode(value["ciphertext"], validate=True),
                    b"academic-sync-job-v1",
                )
            )
            if (
                not all(isinstance(x, str) for x in (uid, operation, token))
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid) is None
                or re.fullmatch(r"[A-Za-z0-9_-]{8,80}", operation) is None
                or not token
                or len(token) > 16384
                or type(issued) is not int
                or not 0 <= now - issued <= 900
            ):
                raise ValueError()
            return uid, operation, token
        except (ValueError, TypeError, KeyError, InvalidTag):
            raise InvalidJob("invalid worker envelope") from None


class AcademicSyncJob:
    def __init__(
        self,
        store: FirestoreRestClient,
        *,
        now: Callable[[], int],
        telemetry: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        self.store, self.now, self.telemetry = store, now, telemetry

    def _document(self) -> dict[str, Any] | None:
        try:
            return self.store.get_user_document("syncJobs", "current")
        except FirestoreNotFound:
            return None

    def read(self) -> dict[str, Any]:
        doc = self._document()
        if doc is None:
            return {"status": "missing"}
        fields = doc["fields"]
        value = json.loads(fields["stateJson"]["stringValue"])
        if (
            value["status"] in ("queued", "running")
            and self.now() - value["started_at"] > LEASE_SECONDS
        ):
            value.update(status="failed", failure_code="worker_deadline_exceeded")
        return dict(value)

    def _write(self, value: dict[str, Any], previous: dict[str, Any] | None) -> None:
        self.store.patch_user_document(
            "syncJobs",
            "current",
            fields={"stateJson": {"stringValue": json.dumps(value, separators=(",", ":"))}},
            expected_update_time=previous["updateTime"] if previous else None,
            create_only=previous is None,
        )

    def start(self, operation: str, enqueue: Callable[[], None]) -> dict[str, Any]:
        previous = self._document()
        current = self.read() if previous else {"status": "missing"}
        if current["status"] in ("queued", "running"):
            return current
        if current.get("operation_id") == operation:
            return current
        value = {
            "operation_id": operation,
            "status": "queued",
            "started_at": self.now(),
            "updated_at": self.now(),
            "failure_code": "",
            "result": None,
        }
        try:
            self._write(value, previous)
        except FirestoreConflict:
            return self.read()
        try:
            enqueue()
        except Exception:
            self.fail(operation, "enqueue_failed")
            raise
        self._emit("academic_sync_job_queued", operation_id=operation)
        return value

    def claim(self, operation: str) -> bool:
        previous = self._document()
        value = self.read()
        if value.get("operation_id") != operation or value["status"] != "queued":
            return False
        value.update(status="running", updated_at=self.now())
        try:
            self._write(value, previous)
        except FirestoreConflict:
            return False
        self._emit("academic_sync_job_started", operation_id=operation)
        return True

    def finish(self, operation: str, result: dict[str, object]) -> None:
        self._terminal(operation, "succeeded", "", result)

    def fail(self, operation: str, reason: str) -> None:
        self._terminal(operation, "failed", reason, None)

    def _terminal(
        self, operation: str, status: str, reason: str, result: dict[str, object] | None
    ) -> None:
        previous = self._document()
        value = self.read()
        if value.get("operation_id") != operation:
            return
        value.update(status=status, failure_code=reason, result=result, updated_at=self.now())
        self._write(value, previous)
        self._emit(
            "academic_sync_job_" + status,
            operation_id=operation,
            failure_code=reason,
            duration_ms=(self.now() - value["started_at"]) * 1000,
        )

    def _emit(self, event: str, **fields: object) -> None:
        emit_telemetry(self.telemetry, event, fields)
