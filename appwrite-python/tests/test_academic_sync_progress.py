from datetime import UTC, datetime
from typing import Any

import pytest

from academic_sync_progress import AcademicSyncProgress


class Store:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []
        self.fail = False

    def patch_user_document(self, *segments: str, fields: dict[str, Any]) -> dict[str, Any]:
        assert segments == ("syncProgress", "current")
        if self.fail:
            raise RuntimeError("write unavailable")
        self.writes.append(fields)
        return {"fields": fields}


def test_progress_uses_completed_server_stages_and_bounded_writes() -> None:
    store = Store()
    events: list[tuple[str, Any]] = []
    progress = AcademicSyncProgress(store, "sync-123", telemetry=lambda e, f: events.append((e, f)))

    def action() -> dict[str, object]:
        progress.observe("academic_sync_stage_completed", {"stage": "siga"})
        progress.observe("academic_sync_stage_completed", {"stage": "siga"})
        progress.observe("academic_sync_stage_completed", {"stage": "moodle"})
        for _ in range(50):
            progress.observe("academic_sync_stage_completed", {"stage": "teaching_plan_import"})
        return {"exceptions": [{"course_code": "ESA019"}]}

    progress.run(action)
    assert len(store.writes) == 4
    assert [row["completed"]["integerValue"] for row in store.writes] == ["0", "1", "2", "3"]
    assert store.writes[-1]["status"] == {"stringValue": "partial"}
    assert events[-1][1]["operation_id"] == "sync-123"


def test_failure_keeps_completed_stages_and_never_logs_secrets() -> None:
    store = Store()
    progress = AcademicSyncProgress(
        store, "sync-123", now=lambda: datetime(2026, 10, 25, tzinfo=UTC),
    )

    def action() -> dict[str, object]:
        progress.observe("other_event", {})
        progress.observe("academic_sync_stage_completed", {"stage": "siga"})
        raise ValueError("password=not-for-logs")

    with pytest.raises(ValueError):
        progress.run(action)
    assert store.writes[-1]["completed"] == {"integerValue": "1"}
    assert store.writes[-1]["failureCode"] == {"stringValue": "ValueError"}
    assert "not-for-logs" not in str(store.writes)


def test_progress_delivery_failure_does_not_fail_sync_or_retry_every_stage() -> None:
    store = Store()
    store.fail = True
    events: list[str] = []
    progress = AcademicSyncProgress(store, "sync-123", telemetry=lambda e, _: events.append(e))
    assert progress.run(lambda: {"exceptions": []}) == {"exceptions": []}
    assert events == ["academic_sync_progress_delivery_failed"]


def test_logging_failure_falls_back_without_blocking_sync(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken_logger(_event: str, _fields: object) -> None:
        raise RuntimeError("password=never-log-this")

    progress = AcademicSyncProgress(Store(), "sync-123", telemetry=broken_logger)
    assert progress.run(lambda: {"exceptions": []}) == {"exceptions": []}
    errors = capsys.readouterr().err
    assert "academic_sync_progress_log_delivery_failed" in errors
    assert "never-log-this" not in errors
