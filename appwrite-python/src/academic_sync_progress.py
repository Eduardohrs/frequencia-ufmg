"""Publish three real sync stages with at most four writes to one user document."""

import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol


class _Store(Protocol):
    def patch_user_document(self, *segments: str, fields: Mapping[str, Any]) -> dict[str, Any]: ...


class AcademicSyncProgress:
    def __init__(
        self,
        store: _Store,
        operation_id: str,
        *,
        now: Callable[[], datetime] | None = None,
        telemetry: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        self._store = store
        self._operation_id = operation_id
        self._now = now or (lambda: datetime.now(UTC))
        self._telemetry = telemetry
        self._started = self._now().isoformat().replace("+00:00", "Z")
        self._completed = 0
        self._disabled = False

    def run(self, action: Callable[[], dict[str, object]]) -> dict[str, object]:
        self._write("running")
        try:
            result = action()
        except Exception as error:
            self._write("failed", failure_code=type(error).__name__)
            raise
        self._completed = 3
        exceptions = result["exceptions"]
        reviews = len(exceptions) if isinstance(exceptions, list) else 0
        self._write("partial" if reviews else "succeeded", reviews=reviews)
        return result

    def observe(self, event: str, fields: Mapping[str, object]) -> None:
        if event != "academic_sync_stage_completed":
            return
        completed = {"siga": 1, "moodle": 2}.get(str(fields.get("stage")), 0)
        if completed > self._completed:
            self._completed = completed
            self._write("running")

    def _write(self, status: str, *, failure_code: str = "", reviews: int = 0) -> None:
        if self._disabled:
            return
        stage = ("siga", "moodle", "plans", "completed")[self._completed]
        fields: dict[str, Any] = {
            "operationId": {"stringValue": self._operation_id},
            "status": {"stringValue": status},
            "stage": {"stringValue": stage},
            "completed": {"integerValue": str(self._completed)},
            "reviewRequired": {"integerValue": str(reviews)},
            "failureCode": {"stringValue": failure_code},
            "startedAt": {"timestampValue": self._started},
            "updatedAt": {"timestampValue": self._now().isoformat().replace("+00:00", "Z")},
        }
        try:
            started = perf_counter()
            self._store.patch_user_document("syncProgress", "current", fields=fields)
        except Exception as error:
            self._disabled = True
            self._emit("academic_sync_progress_delivery_failed", error_type=type(error).__name__,
                       stage=stage, completed=self._completed, status=status,
                       document_path="syncProgress/current")
        else:
            self._emit("academic_sync_progress_published", status=status, completed=self._completed,
                       stage=stage, review_required=reviews, failure_code=failure_code,
                       duration_ms=round((perf_counter() - started) * 1_000, 3))

    def _emit(self, event: str, **fields: object) -> None:
        if self._telemetry is not None:
            try:
                self._telemetry(event, {"operation_id": self._operation_id, **fields})
            except Exception:
                print(json.dumps({"event": "academic_sync_progress_log_delivery_failed",
                                  "operation_id": self._operation_id, "original_event": event}),
                      file=sys.stderr)
