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
    MoodleAuthorizationRequired,
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
EMPTY_DESCRIPTION_RECHECK_SECONDS = 60 * 60
SUBMISSION_RECHECK_SECONDS = 60 * 60


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


def _load_previous_snapshot(
    snapshots: ActivitySnapshotRepository, course_id: str, term: str
) -> dict[str, Any] | None:
    try:
        previous = snapshots.load(course_id)
    except (ActivitySnapshotMissing, InvalidActivitySnapshot):
        return None
    if not isinstance(previous, dict) or previous.get("term") != term:
        return None
    activities = previous.get("activities")
    if not isinstance(activities, list) or any(not isinstance(item, dict) for item in activities):
        return None
    return previous


def _snapshot_by_source(previous: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if previous is None:
        return {}
    return {
        str(activity["source_id"]): activity
        for activity in cast(list[dict[str, Any]], previous["activities"])
        if "source_id" in activity
    }


def _snapshot_epoch(previous: dict[str, Any]) -> int | None:
    value = previous.get("synced_at")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        timestamp = parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp < 0:
        return None
    return int(timestamp)


def _same_activity_index(old: dict[str, Any], current: dict[str, Any]) -> bool:
    keys = ("source_id", "kind", "title", "url", "relevance")
    return all(old.get(key) == current.get(key) for key in keys)


def _detail_is_complete(activity: dict[str, Any]) -> bool:
    required = {
        "description",
        "dates_text",
        "has_due_date",
        "submission_state",
        "submission_text",
        "attachments",
    }
    return required.issubset(activity) and isinstance(activity.get("attachments"), list)


def _detail_can_be_reused(
    activity: dict[str, Any], *, snapshot_epoch: int | None, now: int
) -> bool:
    """Reuse stable details, but bound fields Moodle can change silently.

    Moodle can hide an assignment description until its opening time without
    changing the activity index or reporting an update.  An empty cached
    description therefore needs a bounded retry window; otherwise it would
    remain empty forever after the activity opens.  Submission status is also
    user-specific: for group assignments, a teammate's submission may not be
    reported by the current-user change feed.  Bound assignment reuse so that
    the next refresh eventually reads the activity page again.
    """

    if not _detail_is_complete(activity):
        return False
    if activity.get("kind") == "assignment":
        if snapshot_epoch is None or now < snapshot_epoch:
            return False
        if now - snapshot_epoch >= SUBMISSION_RECHECK_SECONDS:
            return False
    description = activity.get("description")
    if not isinstance(description, str) or description.strip():
        return True
    if snapshot_epoch is None or now < snapshot_epoch:
        return False
    return now - snapshot_epoch < EMPTY_DESCRIPTION_RECHECK_SECONDS


def _bulk_detail_needs_html_fallback(detail: dict[str, Any]) -> bool:
    """Reject bulk payloads that omit fields needed by the offline snapshot.

    ``core_course_get_contents`` does not expose the current student's
    submission state.  That is an honest ``unknown`` value, not a reason to
    request one HTML page per activity.  Description and attachment omissions
    still fall back because those fields are part of the saved offline
    activity contract.  Test doubles from older callers omit the flags and
    remain compatible.
    """

    return any(
        detail.get(flag) is False
        for flag in (
            "_bulk_description_present",
            "_bulk_attachments_present",
        )
    )


def _clean_bulk_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Remove parser-only provenance flags before persisting a snapshot."""

    return {key: value for key, value in detail.items() if not key.startswith("_bulk_")}


def _entry_moodle_course_id(entry: dict[str, Any], default: object) -> int:
    """Return the Moodle course that owns an indexed activity."""

    raw_course_id = entry.get("moodle_course_id", default)
    try:
        moodle_course_id = int(str(raw_course_id))
    except (TypeError, ValueError):
        raise InvalidMoodleResponse("activity_course_id") from None
    if not 1 <= moodle_course_id <= 2_147_483_647:
        raise InvalidMoodleResponse("activity_course_id")
    return moodle_course_id


def _metric(result: dict[str, object], key: str) -> int:
    value = result.get(key, 0)
    return value if type(value) is int and value >= 0 else 0


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
        reused_activities = 0
        bulk_activities = 0
        bulk_submission_unknown = 0
        bulk_fallbacks = 0
        html_activities = 0
        module_bulk_activities = 0
        module_bulk_calls = 0
        module_bulk_failures = 0
        updates_checked = 0
        updates_changed = 0
        activity_entries_seen = 0
        failed: list[dict[str, object]] = []
        pending_snapshots: list[tuple[str, dict[str, Any]]] = []
        pending_policy_updates: list[tuple[str, str, dict[str, Any]]] = []
        courses = self._courses.list_courses()
        mobile_tokens = None
        try:
            mobile_tokens = self._tokens.load(user_id, now=now)
        except (MoodleAuthorizationRequired, MoodleTokenStoreUnavailable, ValueError) as error:
            _emit(
                self._telemetry,
                "moodle_activity_bulk_unavailable",
                {"reason": type(error).__name__, "stage": "token_load"},
            )
        for course in courses:
            course_id = course["id"]
            fields = {"course_id": course_id, "course_code": course["code"], "term": course["term"]}
            course_started = monotonic()

            capture = partial(
                self._capture_snapshot,
                user_id,
                course,
                now,
                snapshots,
                mobile_tokens=mobile_tokens,
                pending_saves=pending_snapshots,
            )
            try:
                force = self._force
                reused = False
                capture_result: dict[str, object] | None = None
                if self._policy is not None:
                    try:
                        previous = snapshots.load(course_id)
                        force = force or previous["term"] != course["term"]
                    except (ActivitySnapshotMissing, InvalidActivitySnapshot):
                        force = force or bool(
                            self._policy.state(course_id, "activities").get("result")
                        )
                    capture_result, reused = self._policy.run(
                        course_id,
                        "activities",
                        course["term"],
                        now=now,
                        fetch=capture,
                        force=force,
                        defer_success=lambda course, source, state: pending_policy_updates.append(
                            (course, source, state)
                        ),
                    )
                else:
                    capture_result = capture()
                if reused:
                    reused_total += 1
                else:
                    updated += 1
                    if capture_result is not None:
                        activity_entries_seen += _metric(capture_result, "activity_count")
                        reused_activities += _metric(capture_result, "reused_count")
                        bulk_activities += _metric(capture_result, "bulk_count")
                        bulk_submission_unknown += _metric(
                            capture_result, "bulk_submission_unknown"
                        )
                        bulk_fallbacks += _metric(capture_result, "bulk_fallbacks")
                        html_activities += _metric(capture_result, "html_count")
                        module_bulk_activities += _metric(capture_result, "module_bulk_count")
                        module_bulk_calls += _metric(capture_result, "module_bulk_calls")
                        module_bulk_failures += _metric(capture_result, "module_bulk_failures")
                        updates_checked += _metric(capture_result, "updates_checked")
                        updates_changed += _metric(capture_result, "updates_changed")
                _emit(
                    self._telemetry,
                    "activity_snapshot_course_decision",
                    {
                        **fields,
                        "outcome": "reused" if reused else "refreshed",
                        "force": force,
                        "duration_ms": round((monotonic() - course_started) * 1_000, 3),
                        "activity_count": _metric(capture_result, "activity_count")
                        if capture_result is not None
                        else None,
                        "consumer": "discipline_activity_view_and_offline_snapshot",
                    },
                )
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
                    "activity_snapshot_course_decision",
                    {
                        **fields,
                        "outcome": "failed_retained_previous",
                        "force": self._force,
                        "duration_ms": round((monotonic() - course_started) * 1_000, 3),
                        "reason": reason,
                        "consumer": "discipline_activity_view_and_offline_snapshot",
                    },
                )
        if pending_snapshots:
            payload_bytes = sum(
                len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode())
                for _, snapshot in pending_snapshots
            )

            def persist_snapshots() -> None:
                save_batch = getattr(snapshots, "save_batch", None)
                if callable(save_batch):
                    save_batch(pending_snapshots)
                    return
                # Compatibility path for small in-memory fakes and older
                # embedders.  Production uses the repository's atomic commit.
                for course_id, snapshot in pending_snapshots:
                    snapshots.save(course_id, snapshot)

            timed_stage(
                "activity_snapshot_persist",
                persist_snapshots,
                telemetry=self._telemetry,
                fields={
                    "snapshot_count": len(pending_snapshots),
                    "snapshot_payload_bytes": payload_bytes,
                    "batch": True,
                },
            )
            if self._policy is not None:
                for course_id, source, state in pending_policy_updates:
                    self._policy.persist_success(course_id, source, state)
        _emit(
            self._telemetry,
            "activity_snapshots_synced",
            {
                "total_courses": len(courses),
                "updated": updated,
                "failed": len(failed),
                **({"reused": reused_total} if self._policy is not None else {}),
                "failed_activities": failed_activities,
                "reused_activities": reused_activities,
                "bulk_activities": bulk_activities,
                "bulk_submission_unknown": bulk_submission_unknown,
                "bulk_fallbacks": bulk_fallbacks,
                "html_activities": html_activities,
                "module_bulk_activities": module_bulk_activities,
                "module_bulk_calls": module_bulk_calls,
                "module_bulk_failures": module_bulk_failures,
                "updates_checked": updates_checked,
                "updates_changed": updates_changed,
                "activity_entries_seen": activity_entries_seen,
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
        self,
        user_id: str,
        course: dict[str, Any],
        now: int,
        snapshots: ActivitySnapshotRepository,
        *,
        mobile_tokens: object | None = None,
        pending_saves: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> dict[str, object]:
        course_id = course["id"]
        fields = {"course_id": course_id, "course_code": course["code"], "term": course["term"]}
        index = self.list_activities(user_id, course_id, now=now)
        entries = cast(list[dict[str, Any]], index["activities"])
        session = self._source(user_id, course_id, now)[1]
        activities: list[dict[str, Any] | None] = [None] * len(entries)
        previous = _load_previous_snapshot(snapshots, course_id, course["term"])
        previous_by_source = _snapshot_by_source(previous)
        incremental_supported = callable(getattr(self._client, "activity_updates_since", None))
        reuse_allowed = incremental_supported and previous is not None
        changed_positions = set(range(len(entries)))
        reused_count = 0
        updates_checked = 0
        updates_changed = 0

        if reuse_allowed:
            previous = cast(dict[str, Any], previous)
            previous_epoch = _snapshot_epoch(previous)
            for position, entry in enumerate(entries):
                old = previous_by_source.get(str(entry["source_id"]))
                if (
                    old is not None
                    and _same_activity_index(old, entry)
                    and _detail_can_be_reused(old, snapshot_epoch=previous_epoch, now=now)
                ):
                    activities[position] = {**old, **entry}
                    changed_positions.discard(position)
                    reused_count += 1
            since = _snapshot_epoch(previous)
            if since is None:
                changed_positions = set(range(len(entries)))
                activities = [None] * len(entries)
                reused_count = 0
            else:
                try:
                    # A canonical discipline may contain activities imported
                    # from one or more metaturmas.  Probe every Moodle course
                    # represented by the index; checking only the canonical
                    # course would silently keep stale metaturma dates.
                    course_by_position: dict[int, int] = {}
                    for position, entry in enumerate(entries):
                        course_by_position[position] = _entry_moodle_course_id(
                            entry, index["moodle_course_id"]
                        )

                    changed_by_course: dict[int, set[int]] = {}
                    for moodle_course_id in sorted(set(course_by_position.values())):
                        updates_checked += 1
                        changed_ids = self._client.activity_updates_since(
                            session.token,
                            term=course["term"],
                            course_id=moodle_course_id,
                            since=since,
                        )
                        if not isinstance(changed_ids, set) or not all(
                            type(value) is int for value in changed_ids
                        ):
                            raise InvalidMoodleResponse("activity_updates_shape")
                        changed_by_course[moodle_course_id] = changed_ids
                    for position, entry in enumerate(entries):
                        if int(str(entry["source_id"])) in changed_by_course.get(
                            course_by_position[position], set()
                        ):
                            changed_positions.add(position)
                            if activities[position] is not None:
                                activities[position] = None
                                reused_count -= 1
                    updates_changed = sum(
                        1
                        for position, entry in enumerate(entries)
                        if int(str(entry["source_id"]))
                        in changed_by_course.get(course_by_position[position], set())
                    )
                except Exception as error:
                    _emit(
                        self._telemetry,
                        "moodle_activity_updates_unavailable",
                        {
                            **fields,
                            "reason": type(error).__name__,
                            "upstream_class": _classify_upstream(error)[0],
                        },
                    )
                    # A failed change check cannot prove that reused details are
                    # current; refresh the complete index through the bulk path.
                    changed_positions = set(range(len(entries)))
                    activities = [None] * len(entries)
                    reused_count = 0

        bulk_count = 0
        bulk_submission_unknown = 0
        bulk_fallbacks = 0
        module_bulk_count = 0
        module_bulk_calls = 0
        module_bulk_failures = 0
        html_positions = set(changed_positions)
        bulk_method = getattr(self._client, "fetch_course_activity_bulk", None)
        bulk_details_complete = getattr(self._client, "bulk_activity_details_complete", True)
        if (
            changed_positions
            and callable(bulk_method)
            and bulk_details_complete is True
            and mobile_tokens is not None
            and getattr(mobile_tokens, "term", None) == course["term"]
        ):
            webservice_token = getattr(mobile_tokens, "webservice_token", None)
            private_token = getattr(mobile_tokens, "private_token", None)
            if isinstance(webservice_token, str) and isinstance(private_token, str):
                try:
                    positions_by_course: dict[int, set[int]] = {}
                    for position in changed_positions:
                        moodle_course_id = _entry_moodle_course_id(
                            entries[position], index["moodle_course_id"]
                        )
                        positions_by_course.setdefault(moodle_course_id, set()).add(position)

                    # Metaturma activities are owned by their own Moodle
                    # course.  Read each distinct course once instead of
                    # sending a metaturma activity to the canonical endpoint.
                    for moodle_course_id, positions in sorted(positions_by_course.items()):
                        bulk_details = timed_stage(
                            "activity_snapshot_bulk_capture",
                            partial(
                                bulk_method,
                                webservice_token=webservice_token,
                                private_token=private_token,
                                term=course["term"],
                                course_id=moodle_course_id,
                            ),
                            telemetry=self._telemetry,
                            fields={
                                **fields,
                                "moodle_course_id": moodle_course_id,
                                "activity_count": len(positions),
                            },
                        )
                        if not isinstance(bulk_details, dict):
                            raise InvalidMoodleResponse("course_activity_bulk_shape")
                        for position in positions:
                            entry = entries[position]
                            detail = bulk_details.get(str(entry["source_id"]))
                            if not isinstance(detail, dict):
                                bulk_fallbacks += 1
                                _emit(
                                    self._telemetry,
                                    "moodle_activity_bulk_detail_fallback",
                                    {
                                        **fields,
                                        "source_id": entry["source_id"],
                                        "kind": entry["kind"],
                                        "reason": "activity_missing_from_bulk_response",
                                        "missing_fields": ["activity"],
                                    },
                                )
                                continue
                            if _bulk_detail_needs_html_fallback(detail):
                                bulk_fallbacks += 1
                                missing_fields = [
                                    field
                                    for field, flag in (
                                        ("description", "_bulk_description_present"),
                                        ("attachments", "_bulk_attachments_present"),
                                    )
                                    if detail.get(flag) is False
                                ]
                                _emit(
                                    self._telemetry,
                                    "moodle_activity_bulk_detail_fallback",
                                    {
                                        **fields,
                                        "source_id": entry["source_id"],
                                        "kind": entry["kind"],
                                        "reason": "missing_bulk_fields",
                                        "missing_fields": missing_fields,
                                    },
                                )
                                continue
                            clean_detail = _clean_bulk_detail(detail)
                            activities[position] = {
                                **entry,
                                **clean_detail,
                                "files": [],
                                "term": course["term"],
                            }
                            html_positions.discard(position)
                            bulk_count += 1
                            bulk_submission_unknown += int(
                                clean_detail.get("submission_state") == "unknown"
                            )
                except Exception as error:
                    _emit(
                        self._telemetry,
                        "moodle_activity_bulk_unavailable",
                        {
                            **fields,
                            "reason": type(error).__name__,
                            "upstream_class": _classify_upstream(error)[0],
                            "activity_count": len(changed_positions),
                        },
                    )
        elif changed_positions and callable(bulk_method) and bulk_details_complete is False:
            _emit(
                self._telemetry,
                "moodle_activity_bulk_skipped",
                {
                    **fields,
                    "reason": "page_only_fields_incomplete",
                    "activity_count": len(changed_positions),
                },
            )

        module_bulk_method = getattr(self._client, "fetch_course_activity_module_bulk", None)
        if (
            html_positions
            and callable(module_bulk_method)
            and mobile_tokens is not None
            and getattr(mobile_tokens, "term", None) == course["term"]
        ):
            webservice_token = getattr(mobile_tokens, "webservice_token", None)
            private_token = getattr(mobile_tokens, "private_token", None)
            if isinstance(webservice_token, str) and isinstance(private_token, str):
                positions_by_module: dict[tuple[int, str], set[int]] = {}
                for position in html_positions:
                    entry = entries[position]
                    key = (
                        _entry_moodle_course_id(entry, index["moodle_course_id"]),
                        str(entry["kind"]),
                    )
                    positions_by_module.setdefault(key, set()).add(position)
                for (moodle_course_id, kind), positions in sorted(positions_by_module.items()):
                    if kind not in {"assign", "quiz"}:
                        continue
                    module_bulk_calls += 1
                    try:
                        module_details = timed_stage(
                            "activity_snapshot_module_bulk_capture",
                            partial(
                                module_bulk_method,
                                webservice_token=webservice_token,
                                private_token=private_token,
                                term=course["term"],
                                course_id=moodle_course_id,
                                kind=kind,
                            ),
                            telemetry=self._telemetry,
                            fields={
                                **fields,
                                "moodle_course_id": moodle_course_id,
                                "kind": kind,
                                "activity_count": len(positions),
                            },
                        )
                        if not isinstance(module_details, dict):
                            raise InvalidMoodleResponse("activity_module_bulk_shape")
                    except Exception as error:
                        module_bulk_failures += 1
                        _emit(
                            self._telemetry,
                            "moodle_activity_module_bulk_unavailable",
                            {
                                **fields,
                                "moodle_course_id": moodle_course_id,
                                "kind": kind,
                                "reason": type(error).__name__,
                                "upstream_class": _classify_upstream(error)[0],
                                "activity_count": len(positions),
                            },
                        )
                        continue
                    for position in positions:
                        entry = entries[position]
                        detail = module_details.get(str(entry["source_id"]))
                        if not isinstance(detail, dict) or _bulk_detail_needs_html_fallback(detail):
                            _emit(
                                self._telemetry,
                                "moodle_activity_module_bulk_detail_fallback",
                                {
                                    **fields,
                                    "source_id": entry["source_id"],
                                    "kind": kind,
                                    "reason": (
                                        "activity_missing_from_module_bulk_response"
                                        if not isinstance(detail, dict)
                                        else "missing_module_bulk_fields"
                                    ),
                                },
                            )
                            continue
                        clean_detail = _clean_bulk_detail(detail)
                        activities[position] = {
                            **entry,
                            **clean_detail,
                            "files": [],
                            "term": course["term"],
                        }
                        html_positions.discard(position)
                        module_bulk_count += 1
                        bulk_submission_unknown += int(
                            clean_detail.get("submission_state") == "unknown"
                        )

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

        outcomes: list[dict[str, object] | None] = []
        if html_positions:
            # Bounded pool: every unresolved activity is attempted even when
            # another one fails, while the final snapshot remains index-ordered.
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                futures = [
                    pool.submit(capture_activity, position, entries[position])
                    for position in sorted(html_positions)
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
        def persist() -> None:
            if pending_saves is None:
                snapshots.save(course_id, snapshot)
                return
            validate_snapshot = getattr(snapshots, "validate_snapshot", None)
            if callable(validate_snapshot):
                validate_snapshot(course_id, snapshot)
            pending_saves.append((course_id, snapshot))

        timed_stage(
            "activity_snapshot_queue" if pending_saves is not None else "activity_snapshot_persist",
            persist,
            telemetry=self._telemetry,
            fields={
                **fields,
                "activity_count": len(activities),
                "snapshot_payload_bytes": payload_bytes,
                "reused_count": reused_count,
                "bulk_count": bulk_count,
                "bulk_submission_unknown": bulk_submission_unknown,
                "bulk_fallbacks": bulk_fallbacks,
                "html_count": len(html_positions),
                "updates_checked": updates_checked,
                "updates_changed": updates_changed,
            },
        )
        return {
            "activity_count": len(activities),
            "snapshot_payload_bytes": payload_bytes,
            "reused_count": reused_count,
            "bulk_count": bulk_count,
            "bulk_submission_unknown": bulk_submission_unknown,
            "bulk_fallbacks": bulk_fallbacks,
            "html_count": len(html_positions),
            "module_bulk_count": module_bulk_count,
            "module_bulk_calls": module_bulk_calls,
            "module_bulk_failures": module_bulk_failures,
            "updates_checked": updates_checked,
            "updates_changed": updates_changed,
        }

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
