"""Coordinate one Moodle synchronization over a shared authenticated client."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

from academic_sync_lineage import MOODLE_ACTIVITY_SNAPSHOT, MOODLE_CALENDAR
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable
from sync_timing import Telemetry, _emit, timed_stage
from ufmg_session_store import UFMGSessionStoreUnavailable


class _Dates(Protocol):
    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]: ...


class _Content(Protocol):
    def discover(self, user_id: str, *, now: int) -> dict[str, object]: ...


class _Capabilities(Protocol):
    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]: ...


class _SnapshotSync(Protocol):
    def __call__(
        self,
        user_id: str,
        now: int,
        content: dict[str, object] | None = None,
    ) -> dict[str, object]: ...


class MoodleSyncService:
    """Run Moodle stages together so their client can reuse the SAML session."""

    def __init__(
        self,
        dates: _Dates,
        content: _Content,
        capabilities: _Capabilities,
        *,
        connection_count: Callable[[], int] = lambda: 0,
        snapshot_sync: _SnapshotSync | None = None,
        telemetry: Telemetry | None = None,
        monotonic: Callable[[], float] | None = None,
        parallel_stages: bool = False,
    ) -> None:
        self._snapshot_sync = snapshot_sync
        self._dates = dates
        self._content = content
        self._capabilities = capabilities
        self._connection_count = connection_count
        self._telemetry = telemetry
        self._monotonic = monotonic
        self._parallel_stages = parallel_stages

    def sync(
        self,
        user_id: str,
        *,
        now: int,
        on_content_discovered: Callable[[dict[str, object]], None] | None = None,
    ) -> dict[str, object]:
        if self._parallel_stages:
            snapshot_sync = self._snapshot_sync
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="moodle-sync") as pool:
                dates_future = pool.submit(
                    self._timed,
                    "moodle_date_import",
                    lambda: self._dates.import_dates(user_id, now=now),
                )
                content_future = pool.submit(
                    self._timed,
                    "moodle_content_discovery",
                    lambda: self._content.discover(user_id, now=now),
                )
                capabilities_future = pool.submit(
                    self._probe_capabilities,
                    user_id,
                    now,
                )
                content = content_future.result()
                if on_content_discovered is not None:
                    on_content_discovered(content)
                # Credential probing may provision the current-term mobile
                # token.  Snapshots must start only after that write is done;
                # calendar/content discovery can remain concurrent.
                capabilities = capabilities_future.result()
                snapshot_future: Future[dict[str, object]] | None = None
                if snapshot_sync is not None:
                    snapshot_future = pool.submit(
                        self._timed,
                        "moodle_activity_snapshots",
                        lambda: snapshot_sync(user_id, now, content),
                    )
                dates = dates_future.result()
                snapshots = self._snapshot_result(snapshot_future)
        else:
            dates = self._timed(
                "moodle_date_import", lambda: self._dates.import_dates(user_id, now=now)
            )
            content = self._timed(
                "moodle_content_discovery", lambda: self._content.discover(user_id, now=now)
            )
            if on_content_discovered is not None:
                on_content_discovered(content)
            capabilities = self._probe_capabilities(user_id, now)
            snapshots = self._snapshot_result(None, user_id=user_id, now=now, content=content)
        _emit(
            self._telemetry,
            "academic_sync_lineage",
            {
                **MOODLE_CALENDAR,
                "source": "moodle_calendar",
                "dataset": "course_dates_and_deadlines",
                "consumer": "agenda_and_course_schedule",
                "extracted": dates.get("total", 0),
                "matched": dates.get("matched", 0),
                "unmatched": dates.get("unmatched", 0),
                "created": dates.get("created", 0),
                "updated": dates.get("updated", 0),
                "unchanged": dates.get("unchanged", 0),
            },
        )
        _emit(
            self._telemetry,
            "academic_sync_lineage",
            {
                **MOODLE_ACTIVITY_SNAPSHOT,
                "source": "moodle_activity_snapshot",
                "dataset": "activity_metadata_and_attachments",
                "consumer": "discipline_activity_view_and_offline_snapshot",
                "updated_courses": (
                    activity_summary.get("updated", 0)
                    if isinstance(activity_summary := snapshots.get("activities"), dict)
                    else 0
                ),
                "failed_courses": (
                    activity_summary.get("failed", 0)
                    if isinstance(activity_summary, dict)
                    else 0
                ),
                "deduplication_key": "course_id+source_id+term",
                "overlaps_calendar_fields": True,
                "overlap_policy": "calendar_owns_agenda_dates; snapshot_owns_activity_details",
            },
        )
        if self._parallel_stages:
            _emit(
                self._telemetry,
                "sync_span_graph",
                {
                    "root": "moodle",
                    "nodes": [
                        {
                            "name": "moodle_date_import",
                            "depends_on": [],
                            "parallel_group": "moodle_stages",
                        },
                        {
                            "name": "moodle_content_discovery",
                            "depends_on": [],
                            "parallel_group": "moodle_stages",
                        },
                        {
                            "name": "moodle_capability_probe",
                            "depends_on": [],
                            "parallel_group": "moodle_stages",
                        },
                        {
                            "name": "moodle_activity_snapshots",
                            "depends_on": ["moodle_content_discovery"],
                            "parallel_group": "after_content_discovery",
                        },
                    ],
                    "join": "moodle_sync_result",
                },
            )
        return {
            **snapshots,
            "dates": dates,
            "content": content,
            "capabilities": capabilities,
            "saml_connections": self._connection_count(),
        }

    def _probe_capabilities(self, user_id: str, now: int) -> dict[str, bool | str] | None:
        try:
            return self._timed(
                "moodle_capability_probe",
                lambda: self._capabilities.probe(user_id, now=now),
            )
        except (
            InvalidMoodleResponse,
            MoodleTokenStoreUnavailable,
            MoodleUnavailable,
            UFMGSessionStoreUnavailable,
            TypeError,
            ValueError,
        ):
            return None

    def _snapshot_result(
        self,
        future: Future[dict[str, object]] | None,
        *,
        user_id: str | None = None,
        now: int | None = None,
        content: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if self._snapshot_sync is None:
            return {}
        try:
            snapshot_sync = self._snapshot_sync
            if future is not None:
                return {"activities": future.result()}
            assert content is not None and user_id is not None and now is not None
            return {
                "activities": self._timed(
                    "moodle_activity_snapshots",
                    lambda: snapshot_sync(user_id, now, content),
                )
            }
        except Exception:
            return {"activities": {"updated": 0, "failed": 1, "failed_courses": []}}

    def _timed[T](self, stage: str, action: Callable[[], T]) -> T:
        options: dict[str, object] = {"telemetry": self._telemetry}
        if self._monotonic is not None:
            options["clock"] = self._monotonic
        return timed_stage(stage, action, **options)  # type: ignore[arg-type]
