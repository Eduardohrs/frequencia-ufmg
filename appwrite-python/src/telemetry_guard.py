"""Telemetry deduplication, budget, and refusal diagnosis for the deployed function.

The production deployment bundles ``appwrite-python/src`` plus only the shared
``frequencia_ufmg`` package ``__init__``/``models`` modules, so the guards that
protect the real log producer must live here and never depend on the backend-only
modules. Repeated reads of the same report inside one execution must not create
new log writes, the deduplication cache and the attempt counter are bounded so diagnostics
cannot grow without limit, and HTTP 429 / RESOURCE_EXHAUSTED refusals keep
their status and error code for diagnosis.
"""

import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_WINDOW_SECONDS = 300.0
MAX_TRACKED_REPORTS = 4096
MAX_TRACKED_DIAGNOSTICS = 1024
MAX_TRACKED_ATTEMPTS = 4096
VOLATILE_FIELDS = frozenset(
    {
        "duration_ms",
        "firestore_duration_ms",
        "queue_wait_ms",
        "received_at_ms",
        "request_id",
    }
)


@dataclass(frozen=True, slots=True)
class TelemetryKey:
    """Immutable identity of one telemetry report."""

    category: str
    action: str
    entity_type: str
    entity_id: str

    def to_hash(self) -> str:
        """Return a stable hash used as deduplication cache key."""
        content = f"{self.category}:{self.action}:{self.entity_type}:{self.entity_id}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _content_hash(fields: Mapping[str, Any] | None) -> str:
    """Hash report content while ignoring volatile timing fields."""
    if not fields:
        return ""
    stable = {name: fields[name] for name in sorted(fields) if name not in VOLATILE_FIELDS}
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TelemetryDeduplicator:
    """Allow one write per report key inside the window, with a bounded cache."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_entries: int = MAX_TRACKED_REPORTS,
        clock: Any = None,
    ) -> None:
        """Initialize the deduplicator with a window and a hard cache budget."""
        self._window = timedelta(seconds=window_seconds)
        self._max_entries = max(1, max_entries)
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._lock = threading.RLock()
        self._last_reports: dict[str, datetime] = {}

    def should_report(self, key: TelemetryKey) -> bool:
        """Return True once per key per window; evict the oldest entry over budget."""
        now = self._clock()
        with self._lock:
            hash_key = key.to_hash()
            last_time = self._last_reports.get(hash_key)
            if last_time is not None and now - last_time < self._window:
                return False
            if hash_key not in self._last_reports and len(self._last_reports) >= self._max_entries:
                oldest = min(self._last_reports, key=lambda item: self._last_reports[item])
                del self._last_reports[oldest]
            self._last_reports[hash_key] = now
            return True

    def clear_old_entries(self) -> int:
        """Drop entries older than the window and return how many were removed."""
        threshold = self._clock() - self._window
        with self._lock:
            old_keys = [key for key, moment in self._last_reports.items() if moment < threshold]
            for key in old_keys:
                del self._last_reports[key]
            return len(old_keys)


class ProductionTelemetryRecorder:
    """Record production reports with deduplication and preserve refusal diagnosis."""

    def __init__(self, deduplicator: TelemetryDeduplicator | None = None) -> None:
        """Initialize with an optional deduplicator."""
        self._deduplicator = deduplicator or TelemetryDeduplicator()
        self._lock = threading.RLock()
        self._diagnostics: dict[str, dict[str, Any]] = {}
        self._attempts: dict[str, int] = {}

    def record_report(
        self,
        category: str,
        action: str,
        entity_type: str,
        entity_id: str,
        fields: Mapping[str, Any] | None = None,
    ) -> bool:
        """Return True when the report may be written; repeated reports are skipped."""
        key = TelemetryKey(
            category,
            action,
            entity_type,
            f"{entity_id}:{_content_hash(fields)}",
        )
        with self._lock:
            hash_key = key.to_hash()
            if hash_key not in self._attempts and len(self._attempts) >= MAX_TRACKED_ATTEMPTS:
                oldest = next(iter(self._attempts))
                del self._attempts[oldest]
            self._attempts[hash_key] = self._attempts.get(hash_key, 0) + 1
        return self._deduplicator.should_report(key)

    def attempt_count(
        self,
        category: str,
        action: str,
        entity_type: str,
        entity_id: str,
        fields: Mapping[str, Any] | None = None,
    ) -> int:
        """Return how many times a report was attempted, including skipped writes."""
        key = TelemetryKey(category, action, entity_type, f"{entity_id}:{_content_hash(fields)}")
        with self._lock:
            return self._attempts.get(key.to_hash(), 0)

    def record_rejection(
        self,
        request_id: str,
        *,
        status_code: int,
        error_code: str,
        retry_after: float | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Preserve the status and error code of a refused write for diagnosis."""
        info: dict[str, Any] = {
            "error_code": error_code,
            "request_id": request_id,
            "retry_after": retry_after,
            "status_code": status_code,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if context:
            info["context"] = dict(context)
        with self._lock:
            over_budget = len(self._diagnostics) >= MAX_TRACKED_DIAGNOSTICS
            if request_id not in self._diagnostics and over_budget:
                oldest = next(iter(self._diagnostics))
                del self._diagnostics[oldest]
            self._diagnostics[request_id] = info
        return info

    def get_diagnosis(self, request_id: str) -> dict[str, Any] | None:
        """Return the recorded refusal diagnosis for a request, if any."""
        with self._lock:
            diagnosis = self._diagnostics.get(request_id)
            return dict(diagnosis) if diagnosis is not None else None


# Global instance used by the deployed function's real log producer.
production_telemetry = ProductionTelemetryRecorder()
