import pytest

from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_sync import MoodleSyncService
from moodle_token_store import MoodleTokenStoreUnavailable
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSessionStoreUnavailable


class _Stage:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    def _run(self, user_id: str, now: int) -> object:
        self.calls.append((user_id, now))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]:
        return self._run(user_id, now)  # type: ignore[return-value]

    def discover(self, user_id: str, *, now: int) -> dict[str, object]:
        return self._run(user_id, now)  # type: ignore[return-value]

    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]:
        return self._run(user_id, now)  # type: ignore[return-value]


def test_sync_returns_all_moodle_stages_from_one_operation() -> None:
    dates = _Stage({"created": 2})
    content = _Stage({"candidate_total": 8})
    capabilities = _Stage({"direct_download_supported": True})

    result = MoodleSyncService(dates, content, capabilities, connection_count=lambda: 1).sync(
        "user-1", now=42
    )

    assert result == {
        "dates": {"created": 2},
        "content": {"candidate_total": 8},
        "capabilities": {"direct_download_supported": True},
        "saml_connections": 1,
    }
    assert dates.calls == content.calls == capabilities.calls == [("user-1", 42)]


@pytest.mark.parametrize(
    "failure",
    [
        InvalidMoodleResponse(),
        MoodleTokenStoreUnavailable(),
        MoodleUnavailable(),
        UFMGSessionStoreUnavailable(),
        TypeError(),
        ValueError(),
    ],
)
def test_sync_keeps_dates_and_content_when_capability_probe_is_optional(
    failure: Exception,
) -> None:
    result = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage(failure),
    ).sync("user-1", now=42)

    assert result["capabilities"] is None


def test_sync_preserves_reauthentication_as_a_required_failure() -> None:
    service = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage(UFMGReauthenticationRequired()),
    )

    with pytest.raises(UFMGReauthenticationRequired):
        service.sync("user-1", now=42)


def test_sync_reports_each_moodle_stage_including_optional_failure() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    ticks = iter([0.0, 0.4, 0.4, 1.1, 1.1, 1.3])
    result = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage(MoodleUnavailable("maintenance")),
        telemetry=lambda event, fields: events.append((event, dict(fields))),
        monotonic=lambda: next(ticks),
    ).sync("user-1", now=42)

    assert result["capabilities"] is None
    assert [event for event, _ in events[:3]] == [
        "academic_sync_stage_completed",
        "academic_sync_stage_completed",
        "academic_sync_stage_failed",
    ]
    assert events[:3] == [
        ("academic_sync_stage_completed", {"stage": "moodle_date_import", "duration_ms": 400}),
        (
            "academic_sync_stage_completed",
            {"stage": "moodle_content_discovery", "duration_ms": 700},
        ),
        (
            "academic_sync_stage_failed",
            {
                "stage": "moodle_capability_probe",
                "duration_ms": 200,
                "exception_type": "MoodleUnavailable",
                "reason": "maintenance",
            },
        ),
    ]
    assert [event for event, _ in events[3:]] == [
        "academic_sync_lineage",
        "academic_sync_lineage",
    ]
    assert events[3][1]["source"] == "moodle_calendar"
    assert events[4][1]["source"] == "moodle_activity_snapshot"


@pytest.mark.parametrize("failure", [False, True])
def test_sync_saves_activity_snapshots_and_reports_failure_without_losing_other_stages(failure):
    logs = []
    seen_content = []

    def capture(user, now, content=None):
        assert (user, now) == ("owner", 42)
        seen_content.append(content)
        if failure:
            raise OSError("snapshot database unavailable")
        return {"updated": 1, "failed": 0, "failed_courses": []}

    result = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage({}),
        snapshot_sync=capture,
        telemetry=lambda event, fields: logs.append((event, fields)),
    ).sync("owner", now=42)
    assert result["dates"] == {"created": 1}
    assert result["activities"]["failed"] == int(failure)
    # The snapshot stage receives the same discovery result from this run.
    assert seen_content == [{"candidate_total": 2}]
    assert any(
        fields["stage"] == "moodle_activity_snapshots" and "duration_ms" in fields
        for _, fields in logs
    )


def test_parallel_sync_runs_independent_stages_and_emits_dependency_graph() -> None:
    logs: list[tuple[str, dict[str, object]]] = []
    seen_content: list[dict[str, object] | None] = []

    def capture(user: str, now: int, content: dict[str, object] | None = None) -> dict[str, object]:
        assert (user, now) == ("owner", 42)
        seen_content.append(content)
        return {"updated": 2, "failed": 0, "failed_courses": []}

    result = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage({"direct_download_supported": True}),
        snapshot_sync=capture,
        telemetry=lambda event, fields: logs.append((event, dict(fields))),
        parallel_stages=True,
    ).sync("owner", now=42)

    assert result["activities"] == {"updated": 2, "failed": 0, "failed_courses": []}
    assert seen_content == [{"candidate_total": 2}]
    graph = [fields for event, fields in logs if event == "sync_span_graph"]
    assert graph and graph[0]["root"] == "moodle"
    assert any(
        node["name"] == "moodle_activity_snapshots"
        and node["depends_on"] == ["moodle_content_discovery"]
        for node in graph[0]["nodes"]
    )

    no_snapshot = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage({}),
        parallel_stages=True,
    ).sync("owner", now=42)
    assert "activities" not in no_snapshot
