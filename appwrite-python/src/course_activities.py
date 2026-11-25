"""Read Moodle activities for an owned course; attachment bytes stay at Moodle."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from mimetypes import guess_type
from time import monotonic
from typing import Any, Protocol, cast

from activity_snapshot_repository import (
    ActivitySnapshotMissing,
    ActivitySnapshotRepository,
    InvalidActivitySnapshot,
)
from course_repository import CourseRepository
from course_sync_policy import CourseSyncPolicy
from moodle_material_catalog_repository import MoodleMaterialCatalogRepository
from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
    _private_file_url,
)
from moodle_token_store import (
    AppwriteMoodleTokenStore,
    MoodleTokenStoreUnavailable,
)
from sync_timing import Telemetry, _emit, timed_stage
from ufmg_session_store import (
    UFMGReauthenticationRequired,
    UFMGSession,
)

DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY = 4
MIN_ACTIVITY_SNAPSHOT_CONCURRENCY = 1
MAX_ACTIVITY_SNAPSHOT_CONCURRENCY = 8
MAX_REPORTED_FAILED_COURSES = 20


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...


class CourseMoodleNotLinked(ValueError):
    """Synchronize Moodle once before opening the course activity catalogue."""


class ActivitySnapshotCaptureFailed(Exception):
    """Some activity detail pages failed; the previous valid snapshot is retained."""

    def __init__(self, failed_count: int, first_reason: str) -> None:
        self.failed_count = failed_count
        self.first_reason = first_reason
        super().__init__(f"{failed_count} activity detail page(s) failed ({first_reason})")


def _bounded_status(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _classify_upstream(error: BaseException) -> tuple[str, int | None]:
    """Bounded upstream classification for telemetry; never bodies, cookies or tokens."""
    if isinstance(error, MoodleUnavailable):
        if error.timed_out:
            return "timeout", _bounded_status(error.upstream_status)
        status = _bounded_status(error.upstream_status)
        if status is not None:
            return f"http_{status}", status
        return "unavailable", None
    if isinstance(error, InvalidMoodleResponse):
        status = _bounded_status(error.details.get("upstream_status"))
        if status is not None:
            return f"http_{status}", status
        return "parser", None
    return "error", None


class CourseActivityService:
    def __init__(
        self,
        courses: CourseRepository,
        catalog: MoodleMaterialCatalogRepository,
        sessions: _Sessions,
        client: MoodleStructuredDatesClient,
        tokens: AppwriteMoodleTokenStore,
        *,
        telemetry: Telemetry | None = None,
        policy: CourseSyncPolicy | None = None,
        force: bool = False,
        max_workers: int = DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY,
    ) -> None:
        self._courses, self._catalog, self._sessions = courses, catalog, sessions
        self._client, self._tokens = client, tokens
        self._telemetry = telemetry
        self._policy, self._force = policy, force
        self._max_workers = min(
            max(MIN_ACTIVITY_SNAPSHOT_CONCURRENCY, max_workers), MAX_ACTIVITY_SNAPSHOT_CONCURRENCY
        )

    def _source(
        self, user_id: str, course_id: str, now: int
    ) -> tuple[dict[str, Any], UFMGSession, int]:
        course = self._courses.get_course(course_id)
        catalogs = self._catalog.list_catalog([course])
        if (
            not catalogs
            or catalogs[0]["status"] not in {"found", "empty"}
            or catalogs[0]["moodle_course_id"] is None
        ):
            raise CourseMoodleNotLinked("course Moodle link unavailable")
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        return course, session, int(str(catalogs[0]["moodle_course_id"]))

    def sync_snapshots(
        self, user_id: str, *, now: int, snapshots: ActivitySnapshotRepository
    ) -> dict[str, object]:
        started = monotonic()
        updated = 0
        reused_total = 0
        failed_activities = 0
        failed: list[dict[str, object]] = []
        courses = self._courses.list_courses()
        for course in courses:
            course_id = course["id"]
            fields = {"course_id": course_id, "course_code": course["code"], "term": course["term"]}

            capture = partial(self._capture_snapshot, user_id, course, now, snapshots)
            try:
                force = self._force
                reused = False
                if self._policy is not None:
                    try:
                        previous = snapshots.load(course_id)
                        force = force or previous["term"] != course["term"]
                    except (ActivitySnapshotMissing, InvalidActivitySnapshot):
                        force = force or bool(
                            self._policy.state(course_id, "activities").get("result")
                        )
                    _, reused = self._policy.run(
                        course_id, "activities", course["term"], now=now, fetch=capture, force=force
                    )
                else:
                    capture()
                if reused:
                    reused_total += 1
                else:
                    updated += 1
            except Exception as error:
                if isinstance(error, ActivitySnapshotCaptureFailed):
                    reason = error.first_reason
                    failed_activities += error.failed_count
                elif isinstance(error, InvalidMoodleResponse):
                    reason = error.reason
                else:
                    reason = type(error).__name__
                issue = {
                    **fields,
                    "reason": reason,
                    "retained_previous": True,
                }
                failed.append(issue)
                _emit(self._telemetry, "activity_snapshot_sync_failed", issue)
        _emit(
            self._telemetry,
            "activity_snapshots_synced",
            {
                "total_courses": len(courses),
                "updated": updated,
                "failed": len(failed),
                **({"reused": reused_total} if self._policy is not None else {}),
                "failed_activities": failed_activities,
                "concurrency": self._max_workers,
                "duration_ms": round((monotonic() - started) * 1000),
            },
        )
        return {
            "updated": updated,
            "failed": len(failed),
            "failed_courses": failed[:MAX_REPORTED_FAILED_COURSES],
            **({"reused": reused_total} if self._policy is not None else {}),
        }

    def _capture_snapshot(
        self, user_id: str, course: dict[str, Any], now: int, snapshots: ActivitySnapshotRepository
    ) -> dict[str, object]:
        course_id = course["id"]
        fields = {"course_id": course_id, "course_code": course["code"], "term": course["term"]}
        index = self.list_activities(user_id, course_id, now=now)
        entries = cast(list[dict[str, Any]], index["activities"])
        session = self._source(user_id, course_id, now)[1]
        activities: list[dict[str, Any] | None] = [None] * len(entries)

        def capture_activity(position: int, entry: dict[str, Any]) -> dict[str, object] | None:
            """Fetch one activity detail; return a bounded failure record or None."""
            started = monotonic()
            try:
                detail = timed_stage(
                    "activity_snapshot_capture",
                    partial(
                        self._client.fetch_activity,
                        session.token,
                        term=course["term"],
                        source_id=int(entry["source_id"]),
                        kind=str(entry["kind"]),
                    ),
                    telemetry=self._telemetry,
                    fields={
                        **fields,
                        "source_id": entry["source_id"],
                        "kind": entry["kind"],
                        "title": entry["title"],
                    },
                )
            except Exception as error:
                upstream_class, upstream_status = _classify_upstream(error)
                failure: dict[str, object] = {
                    **fields,
                    "source_id": entry["source_id"],
                    "kind": entry["kind"],
                    "reason": error.reason
                    if isinstance(error, InvalidMoodleResponse)
                    else type(error).__name__,
                    "exception_type": type(error).__name__,
                    "upstream_class": upstream_class,
                    "duration_ms": round((monotonic() - started) * 1000),
                    "attempt": 1,
                }
                if upstream_status is not None:
                    failure["upstream_status"] = upstream_status
                _emit(self._telemetry, "activity_snapshot_activity_failed", failure)
                return failure
            activities[position] = {**entry, **detail, "files": [], "term": course["term"]}
            return None

        # Bounded pool: every activity is attempted even when others fail, and the
        # snapshot order stays equal to the index order regardless of completion order.
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = [
                pool.submit(capture_activity, position, entry)
                for position, entry in enumerate(entries)
            ]
            outcomes = [future.result() for future in futures]
        failures = [outcome for outcome in outcomes if outcome is not None]
        if failures:
            raise ActivitySnapshotCaptureFailed(
                failed_count=len(failures), first_reason=str(failures[0]["reason"])
            )
        snapshot = {
            "course_id": course_id,
            "term": course["term"],
            "synced_at": datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z"),
            "activities": cast(list[dict[str, Any]], activities),
        }
        payload_bytes = len(
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        )
        timed_stage(
            "activity_snapshot_persist",
            partial(snapshots.save, course_id, snapshot),
            telemetry=self._telemetry,
            fields={
                **fields,
                "activity_count": len(activities),
                "snapshot_payload_bytes": payload_bytes,
            },
        )
        return {"activity_count": len(activities), "snapshot_payload_bytes": payload_bytes}

    def authorize_saved(
        self, user_id: str, course_id: str, detail: dict[str, Any], *, now: int
    ) -> dict[str, Any]:
        # A normal read never calls Moodle, renews a session or refreshes a token.
        files = []
        try:
            tokens = self._tokens.load(user_id, now=now)
            if tokens is not None and tokens.term == detail["term"]:
                for attachment in detail["attachments"]:
                    files.append(
                        {
                            "name": attachment["name"],
                            "url": _private_file_url(
                                attachment["url"],
                                "/" + detail["term"].replace("-", ""),
                                tokens.private_token,
                            ),
                            "size": 0,
                            "mime_type": guess_type(attachment["name"])[0]
                            or "application/octet-stream",
                        }
                    )
        except (MoodleTokenStoreUnavailable, ValueError) as error:
            _emit(
                self._telemetry,
                "activity_snapshot_download_unavailable",
                {
                    "course_id": course_id,
                    "source_id": detail["source_id"],
                    "reason": type(error).__name__,
                    "stage": "saved_download_authorization",
                },
            )
        return {**detail, "files": files}

    def list_activities(self, user_id: str, course_id: str, *, now: int) -> dict[str, object]:
        course, session, moodle_id = self._source(user_id, course_id, now)
        entries = timed_stage(
            "course_activity_index",
            lambda: self._client.list_activities(
                session.token, term=course["term"], course_id=moodle_id, course_code=course["code"]
            ),
            telemetry=self._telemetry,
            fields={
                "course_id": course_id,
                "course_code": course["code"],
                "moodle_course_id": moodle_id,
            },
        )
        _emit(
            self._telemetry,
            "course_activities_loaded",
            {"course_id": course_id, "activity_count": len(entries), "term": course["term"]},
        )
        return {
            "activities": entries,
            "course_id": course_id,
            "term": course["term"],
            "moodle_course_id": str(moodle_id),
        }
