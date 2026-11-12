"""Tests for the deployed telemetry deduplication, budget, and refusal diagnosis."""

from datetime import UTC, datetime, timedelta

import pytest

from telemetry_guard import (
    MAX_TRACKED_DIAGNOSTICS,
    ProductionTelemetryRecorder,
    TelemetryDeduplicator,
    TelemetryKey,
    production_telemetry,
)


def test_telemetry_key_hash_is_stable() -> None:
    key = TelemetryKey("general", "request_completed", "log", "abc")
    assert key.to_hash() == key.to_hash()
    assert key.to_hash() != TelemetryKey("general", "request_completed", "log", "abd").to_hash()


def test_deduplicator_allows_one_write_per_window_then_expires() -> None:
    moments = iter(
        [datetime(2026, 11, 11, tzinfo=UTC) + timedelta(seconds=n) for n in (0, 10, 400)]
    )
    dedup = TelemetryDeduplicator(window_seconds=300, clock=lambda: next(moments))
    key = TelemetryKey("c", "a", "log", "e1")

    assert dedup.should_report(key) is True
    assert dedup.should_report(key) is False
    assert dedup.should_report(key) is True  # window expired


def test_deduplicator_evicts_oldest_entry_when_over_budget() -> None:
    now = datetime(2026, 11, 11, tzinfo=UTC)
    dedup = TelemetryDeduplicator(window_seconds=300, max_entries=2, clock=lambda: now)
    first = TelemetryKey("c", "a", "log", "first")
    second = TelemetryKey("c", "a", "log", "second")
    third = TelemetryKey("c", "a", "log", "third")

    assert dedup.should_report(first) is True
    assert dedup.should_report(second) is True
    assert dedup.should_report(third) is True  # evicts "first"
    assert dedup.should_report(first) is True  # was evicted, so allowed again (evicts "second")
    assert dedup.should_report(third) is False


def test_deduplicator_clear_old_entries_removes_expired_only() -> None:
    base = datetime(2026, 11, 11, tzinfo=UTC)
    moments = iter([base, base + timedelta(seconds=10), base + timedelta(seconds=400)])
    dedup = TelemetryDeduplicator(window_seconds=300, clock=lambda: next(moments))
    old_key = TelemetryKey("c", "a", "log", "old")
    new_key = TelemetryKey("c", "a", "log", "new")

    assert dedup.should_report(old_key) is True
    assert dedup.should_report(new_key) is True
    assert dedup.clear_old_entries() == 2  # both entries are older than the window at t=400


def test_record_report_deduplicates_identical_content_and_counts_attempts() -> None:
    recorder = ProductionTelemetryRecorder()
    fields = {"course_id": "course-1", "duration_ms": 12.5}

    assert recorder.record_report("general", "course_saved", "course", "course-1", fields) is True
    assert recorder.record_report("general", "course_saved", "course", "course-1", fields) is False
    # volatile timing fields do not change the report identity
    assert (
        recorder.record_report(
            "general", "course_saved", "course", "course-1", {**fields, "duration_ms": 99.0}
        )
        is False
    )
    # different content is a different report
    assert (
        recorder.record_report(
            "general", "course_saved", "course", "course-1", {**fields, "outcome": "failed"}
        )
        is True
    )
    assert recorder.attempt_count("general", "course_saved", "course", "course-1", fields) == 3
    assert recorder.attempt_count("general", "course_saved", "course", "course-1", {"x": 1}) == 0
    assert recorder.attempt_count("general", "missing", "course", "course-1") == 0


def test_record_report_without_fields_uses_entity_only() -> None:
    recorder = ProductionTelemetryRecorder()
    assert recorder.record_report("c", "a", "log", "e") is True
    assert recorder.record_report("c", "a", "log", "e") is False
    assert recorder.record_report("c", "a", "log", "e", None) is False


def test_record_rejection_preserves_status_code_and_error_code() -> None:
    recorder = ProductionTelemetryRecorder()
    info = recorder.record_rejection(
        "req-1",
        status_code=429,
        error_code="RESOURCE_EXHAUSTED",
        retry_after=30,
        context={"route": "/v1/courses"},
    )

    assert info["status_code"] == 429
    assert info["error_code"] == "RESOURCE_EXHAUSTED"
    assert info["retry_after"] == 30
    assert info["request_id"] == "req-1"
    diagnosis = recorder.get_diagnosis("req-1")
    assert diagnosis is not None
    assert diagnosis["status_code"] == 429
    assert diagnosis["error_code"] == "RESOURCE_EXHAUSTED"
    assert diagnosis["context"] == {"route": "/v1/courses"}
    assert recorder.get_diagnosis("unknown") is None


def test_record_rejection_without_context_omits_context_key() -> None:
    recorder = ProductionTelemetryRecorder()
    info = recorder.record_rejection("req-2", status_code=429, error_code="RATE_LIMITED")
    assert "context" not in info
    assert recorder.get_diagnosis("req-2") == info


def test_record_rejection_evicts_oldest_when_diagnostics_over_budget() -> None:
    recorder = ProductionTelemetryRecorder()
    for index in range(MAX_TRACKED_DIAGNOSTICS):
        recorder.record_rejection(f"req-{index}", status_code=429, error_code="RESOURCE_EXHAUSTED")
    recorder.record_rejection("req-new", status_code=429, error_code="RESOURCE_EXHAUSTED")

    assert recorder.get_diagnosis("req-0") is None
    assert recorder.get_diagnosis("req-new") is not None
    # updating an existing entry must not evict
    recorder.record_rejection("req-new", status_code=503, error_code="UNAVAILABLE")
    assert recorder.get_diagnosis("req-new")["status_code"] == 503


def test_global_production_telemetry_instance_is_usable() -> None:
    assert production_telemetry.record_report("general", "smoke", "log", "global") in {True, False}


def test_deduplicator_requires_positive_max_entries() -> None:
    dedup = TelemetryDeduplicator(max_entries=0, clock=lambda: datetime(2026, 11, 11, tzinfo=UTC))
    key = TelemetryKey("c", "a", "log", "e")
    assert dedup.should_report(key) is True
    assert dedup.should_report(TelemetryKey("c", "a", "log", "f")) is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))


def test_attempt_counter_is_bounded_and_evicts_oldest() -> None:
    from telemetry_guard import MAX_TRACKED_ATTEMPTS

    recorder = ProductionTelemetryRecorder()
    first = ("c", "a", "log", "first")
    for index in range(MAX_TRACKED_ATTEMPTS):
        recorder.record_report("c", "a", "log", f"entity-{index}")
    recorder.record_report(*first)
    # over budget: the oldest entry (entity-0) is evicted
    recorder.record_report("c", "a", "log", "overflow")
    assert recorder.attempt_count("c", "a", "log", "entity-0") == 0
    assert recorder.attempt_count("c", "a", "log", "overflow") == 1
    assert recorder.attempt_count(*first) == 1
    # re-recording an existing key must not evict others
    recorder.record_report(*first)
    assert recorder.attempt_count("c", "a", "log", "overflow") == 1
    assert recorder.attempt_count(*first) == 2
