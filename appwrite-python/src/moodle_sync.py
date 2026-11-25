"""Coordinate one Moodle synchronization over a shared authenticated client."""

from collections.abc import Callable
from typing import Protocol

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


class MoodleSyncService:
    """Run Moodle stages together so their client can reuse the SAML session."""

    def __init__(
        self,
        dates: _Dates,
        content: _Content,
        capabilities: _Capabilities,
        *,
        connection_count: Callable[[], int] = lambda: 0,
        snapshot_sync: Callable[[str, int], dict[str, object]] | None = None,
        telemetry: Telemetry | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._snapshot_sync = snapshot_sync
        self._dates = dates
        self._content = content
        self._capabilities = capabilities
        self._connection_count = connection_count
        self._telemetry = telemetry
        self._monotonic = monotonic

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        dates = self._timed(
            "moodle_date_import", lambda: self._dates.import_dates(user_id, now=now)
        )
        content = self._timed(
            "moodle_content_discovery", lambda: self._content.discover(user_id, now=now)
        )
        try:
            capabilities: dict[str, bool | str] | None = self._timed(
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
            capabilities = None
        snapshots = {}
        snapshot_sync = self._snapshot_sync
        if snapshot_sync is not None:
            try:
                snapshots["activities"] = self._timed(
                    "moodle_activity_snapshots", lambda: snapshot_sync(user_id, now)
                )
            except Exception:
                snapshots["activities"] = {"updated": 0, "failed": 1, "failed_courses": []}
        _emit(
            self._telemetry,
            "academic_sync_lineage",
            {
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
                "source": "moodle_activity_snapshot",
                "dataset": "activity_metadata_and_attachments",
                "consumer": "discipline_activity_view_and_offline_snapshot",
                "updated_courses": snapshots.get("activities", {}).get("updated", 0)
                if isinstance(snapshots.get("activities"), dict)
                else 0,
                "failed_courses": snapshots.get("activities", {}).get("failed", 0)
                if isinstance(snapshots.get("activities"), dict)
                else 0,
                "deduplication_key": "course_id+source_id+term",
                "overlaps_calendar_fields": True,
                "overlap_policy": "calendar_owns_agenda_dates; snapshot_owns_activity_details",
            },
        )
        return {
            **snapshots,
            "dates": dates,
            "content": content,
            "capabilities": capabilities,
            "saml_connections": self._connection_count(),
        }

    def _timed[T](self, stage: str, action: Callable[[], T]) -> T:
        options: dict[str, object] = {"telemetry": self._telemetry}
        if self._monotonic is not None:
            options["clock"] = self._monotonic
        return timed_stage(stage, action, **options)  # type: ignore[arg-type]
