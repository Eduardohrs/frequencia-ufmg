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

# HTML enrichment is the measured slow path for quiz snapshots.  Eight is the
# existing hard cap and keeps the pool bounded while halving the number of
# waves for the observed 11-page fallback; deployments can lower it through
# ``MOODLE_ACTIVITY_SNAPSHOT_CONCURRENCY`` if Moodle rate-limits the account.
DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY = 8
MIN_ACTIVITY_SNAPSHOT_CONCURRENCY = 1
MAX_ACTIVITY_SNAPSHOT_CONCURRENCY = 8
MAX_REPORTED_FAILED_COURSES = 20
EMPTY_DESCRIPTION_RECHECK_SECONDS = 60 * 60
SUBMISSION_RECHECK_SECONDS = 60 * 60
# Sentinel for "caller did not load the previous snapshot" so a sync run can
# pass an explicit None (no previous snapshot) without a second Firestore read.
_PREVIOUS_UNSET: Any = object()


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...


class CourseMoodleNotLinked(ValueError):
    """Synchronize Moodle once before opening the course activity catalogue."""


class ActivitySnapshotCaptureFailed(Exception):
    """Some activity detail pages failed; the previous valid snapshot is retained."""

    def __init__(
        self,
        failed_count: int,
        first_reason: str,
        *,
        metrics: dict[str, object] | None = None,
    ) -> None:
        self.failed_count = failed_count
        self.first_reason = first_reason
        self.metrics = metrics or {}
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
    return _validate_previous(previous, term)


def _validate_previous(previous: object, term: str) -> dict[str, Any] | None:
    """Return the previous snapshot only when it belongs to the current term."""
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


def _module_detail_is_empty(detail: dict[str, Any]) -> bool:
    """Return whether a bulk detail has no useful HTML enrichment payload.

    Calendar fields are intentionally excluded here.  The module bulk response
    already owns due dates; requesting an HTML page only to rediscover those
    dates is the N+1 path this service is trying to avoid.  The helper is used
    for quiz responses, whose HTML page in the UFMG installation has been
    observed to return no description or attachments.
    """

    description = detail.get("description")
    return not (
        isinstance(description, str)
        and description.strip()
        or bool(detail.get("attachments"))
        or bool(detail.get("files"))
    )


def _merge_activity_details(
    structured: dict[str, Any], html: dict[str, Any]
) -> dict[str, Any]:
    """Fill structured bulk gaps from HTML without erasing known values."""

    merged = {**structured, **html}
    for key in ("description", "dates_text", "attachments"):
        if not html.get(key) and structured.get(key):
            merged[key] = structured[key]
    merged["has_due_date"] = bool(structured.get("has_due_date")) or bool(
        html.get("has_due_date")
    )
    return merged


def _clean_activity_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Remove bulk and HTML diagnostic fields before persisting a snapshot."""

    return {
        key: value
        for key, value in detail.items()
        if not key.startswith("_bulk_") and not key.startswith("_html_")
    }


def _html_detail_quality(detail: dict[str, Any]) -> dict[str, object]:
    """Classify what an HTML fallback actually returned.

    Empty optional content is evidence about the page, not a transport failure.
    The distinction is kept in telemetry and never changes the snapshot schema.
    """

    description = detail.get("description")
    attachments = detail.get("attachments")
    description_chars = detail.get("_html_description_chars")
    if type(description_chars) is not int or description_chars < 0:
        description_chars = len(description.strip()) if isinstance(description, str) else 0
    attachment_count = detail.get("_html_attachment_count")
    if type(attachment_count) is not int or attachment_count < 0:
        attachment_count = len(attachments) if isinstance(attachments, list) else 0
    raw_empty = detail.get("_html_empty_fields")
    if isinstance(raw_empty, list) and all(isinstance(item, str) for item in raw_empty):
        empty_fields = [item for item in ("description", "attachments") if item in raw_empty]
        metadata_source = "client"
    else:
        empty_fields = []
        if description_chars == 0:
            empty_fields.append("description")
        if attachment_count == 0:
            empty_fields.append("attachments")
        metadata_source = "derived"
    outcome = "complete"
    if len(empty_fields) == 2:
        outcome = "empty_fields"
    elif empty_fields:
        outcome = "partial"
    response_status = detail.get("_html_response_status")
    if type(response_status) is not int or not 100 <= response_status <= 599:
        response_status = 200
    response_bytes = detail.get("_html_response_bytes")
    if type(response_bytes) is not int or response_bytes < 0:
        response_bytes = None
    return {
        "response_status": response_status,
        "response_bytes": response_bytes,
        "description_chars": description_chars,
        "attachment_count": attachment_count,
        "empty_fields": empty_fields,
        "outcome": outcome,
        "metadata_source": metadata_source,
    }


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


def _metric_map(result: dict[str, object], key: str) -> dict[str, int]:
    value = result.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(name): count
        for name, count in value.items()
        if type(count) is int and count >= 0
    }


def _merge_metric_map(target: dict[str, int], result: dict[str, object], key: str) -> None:
    for name, count in _metric_map(result, key).items():
        target[name] = target.get(name, 0) + count


def _count_fallback(
    by_kind: dict[str, int], by_reason: dict[str, int], kind: str, reason: str
) -> None:
    """Classify one HTML fallback so the run summary stays evidence-based."""
    by_kind[kind] = by_kind.get(kind, 0) + 1
    by_reason[reason] = by_reason.get(reason, 0) + 1


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
        update_workers: int = 1,
    ) -> None:
        self._courses, self._catalog, self._sessions = courses, catalog, sessions
        self._client, self._tokens = client, tokens
        self._telemetry = telemetry
        self._policy, self._force = policy, force
        self._max_workers = min(
            max(MIN_ACTIVITY_SNAPSHOT_CONCURRENCY, max_workers), MAX_ACTIVITY_SNAPSHOT_CONCURRENCY
        )
        if not 1 <= update_workers <= MAX_ACTIVITY_SNAPSHOT_CONCURRENCY:
            raise ValueError("invalid activity update concurrency")
        self._update_workers = update_workers
        self._catalog_reads = 0
    def _source(
        self,
        user_id: str,
        course_id: str,
        now: int,
        discovered: dict[str, dict[str, object]] | None = None,
    ) -> tuple[dict[str, Any], UFMGSession, int]:
        course = self._courses.get_course(course_id)
        entry: dict[str, object] | None = None
        if discovered is not None:
            candidate = discovered.get(course_id)
            if isinstance(candidate, dict):
                entry = candidate
        if entry is None:
            # Only reached outside a full sync or for courses the shared
            # discovery result did not cover; counted for read telemetry.
            self._catalog_reads += 1
            catalogs = self._catalog.list_catalog([course])
            entry = catalogs[0] if catalogs else None
        if (
            entry is None
            or entry.get("status") not in {"found", "empty"}
            or entry.get("moodle_course_id") is None
        ):
            raise CourseMoodleNotLinked("course Moodle link unavailable")
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        return course, session, int(str(entry["moodle_course_id"]))

    def sync_snapshots(
        self,
        user_id: str,
        *,
        now: int,
        snapshots: ActivitySnapshotRepository,
        discovered: list[dict[str, object]] | None = None,
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
        html_skipped = 0
        updates_checked = 0
        updates_changed = 0
        activity_entries_seen = 0
        fallback_by_kind: dict[str, int] = {}
        fallback_reasons: dict[str, int] = {}
        html_quality_counts: dict[str, int] = {}
        html_empty_field_counts: dict[str, int] = {}
        failed: list[dict[str, object]] = []
        pending_snapshots: list[tuple[str, dict[str, Any]]] = []
        pending_policy_updates: list[tuple[str, str, dict[str, Any]]] = []
        module_bulk_capabilities: dict[str, bool] = {}
        courses = self._courses.list_courses()
        discovered_map = (
            {
                str(course["course_id"]): course
                for course in discovered
                if isinstance(course, dict) and isinstance(course.get("course_id"), str)
            }
            if discovered is not None
            else None
        )
        policy_state_reads = 0
        self._catalog_reads = 0
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
            fields = {
                "course_id": course_id,
                "course_code": course["code"],
                "term": course["term"],
            }
            course_started = monotonic()

            try:
                # One snapshot read and at most one policy-state read per
                # course: both are reused by the capture step below instead of
                # being loaded again per consumer.
                try:
                    raw_previous = snapshots.load(course_id)
                except (ActivitySnapshotMissing, InvalidActivitySnapshot):
                    raw_previous = None
                policy_state: dict[str, Any] | None = None
                if self._policy is not None and raw_previous is None:
                    policy_state = self._policy.state(course_id, "activities")
                    policy_state_reads += 1
                previous_snapshot = _validate_previous(raw_previous, course["term"])
                capture = partial(
                    self._capture_snapshot,
                    user_id,
                    course,
                    now,
                    snapshots,
                    mobile_tokens=mobile_tokens,
                    module_bulk_capabilities=module_bulk_capabilities,
                    pending_saves=pending_snapshots,
                    previous_snapshot=previous_snapshot,
                    discovered=discovered_map,
                )
                force = self._force
                reused = False
                capture_result: dict[str, object] | None = None
                if self._policy is not None:
                    if raw_previous is not None:
                        force = force or raw_previous["term"] != course["term"]
                    else:
                        force = force or bool((policy_state or {}).get("result"))
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
                        state=policy_state,
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
                        html_skipped += _metric(capture_result, "html_skipped_count")
                        module_bulk_activities += _metric(capture_result, "module_bulk_count")
                        module_bulk_calls += _metric(capture_result, "module_bulk_calls")
                        module_bulk_failures += _metric(capture_result, "module_bulk_failures")
                        updates_checked += _metric(capture_result, "updates_checked")
                        updates_changed += _metric(capture_result, "updates_changed")
                        _merge_metric_map(fallback_by_kind, capture_result, "fallback_by_kind")
                        _merge_metric_map(fallback_reasons, capture_result, "fallback_reasons")
                        _merge_metric_map(
                            html_quality_counts, capture_result, "html_quality_counts"
                        )
                        _merge_metric_map(
                            html_empty_field_counts, capture_result, "html_empty_field_counts"
                        )
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
                    _merge_metric_map(
                        html_quality_counts, error.metrics, "html_quality_counts"
                    )
                    _merge_metric_map(
                        html_empty_field_counts, error.metrics, "html_empty_field_counts"
                    )
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

            def persist_snapshots() -> dict[str, str]:
                save_batch = getattr(snapshots, "save_batch", None)
                if callable(save_batch):
                    result = save_batch(pending_snapshots)
                    return result if isinstance(result, dict) else {}
                # Compatibility path for small in-memory fakes and older
                # embedders.  Production uses the repository's atomic commit.
                failures: dict[str, str] = {}
                for course_id, snapshot in pending_snapshots:
                    try:
                        snapshots.save(course_id, snapshot)
                    except Exception as error:
                        failures[course_id] = type(error).__name__
                return failures

            persistence_failures = timed_stage(
                "activity_snapshot_persist",
                persist_snapshots,
                telemetry=self._telemetry,
                fields={
                    "snapshot_count": len(pending_snapshots),
                    "snapshot_payload_bytes": payload_bytes,
                    "batch": True,
                },
            )
            for course_id, reason in persistence_failures.items():
                course = next(
                    (item for item in courses if item["id"] == course_id),
                    {"id": course_id, "code": "unknown", "term": "unknown"},
                )
                issue = {
                    "course_id": course_id,
                    "course_code": course["code"],
                    "term": course["term"],
                    "reason": "firestore_snapshot_write_failed",
                    "exception_type": reason,
                    "retained_previous": True,
                    "stage": "activity_snapshot_persist",
                }
                failed.append(issue)
                updated = max(0, updated - 1)
                _emit(self._telemetry, "activity_snapshot_persistence_failed", issue)
            if persistence_failures:
                pending_policy_updates = [
                    item for item in pending_policy_updates if item[0] not in persistence_failures
                ]
            if self._policy is not None:
                # One batched commit for every deferred policy success instead of
                # one Firestore patch per course.
                self._policy.persist_success_batch(pending_policy_updates)
        _emit(
            self._telemetry,
            "sync_read_cache",
            {
                "stage": "moodle_activity_snapshots",
                "snapshot_reads": len(courses),
                "policy_state_reads": policy_state_reads,
                "catalog_reads": self._catalog_reads,
                "discovery_shared_courses": len(courses) - self._catalog_reads,
                "policy_write_batch": bool(pending_policy_updates),
                "snapshot_write_batch": bool(pending_snapshots),
            },
        )
        _emit(
            self._telemetry,
            "activity_snapshots_synced",
            {
                "total_courses": len(courses),
                "force": self._force,
                "updated": updated,
                "failed": len(failed),
                **({"reused": reused_total} if self._policy is not None else {}),
                "failed_activities": failed_activities,
                "reused_activities": reused_activities,
                "bulk_activities": bulk_activities,
                "bulk_submission_unknown": bulk_submission_unknown,
                "bulk_fallbacks": bulk_fallbacks,
                "html_activities": html_activities,
                "html_skipped_count": html_skipped,
                "module_bulk_activities": module_bulk_activities,
                "module_bulk_calls": module_bulk_calls,
                "module_bulk_failures": module_bulk_failures,
                "updates_checked": updates_checked,
                "updates_changed": updates_changed,
                "activity_entries_seen": activity_entries_seen,
                "fallback_by_kind": fallback_by_kind,
                "fallback_reasons": fallback_reasons,
                "html_quality_counts": html_quality_counts,
                "html_empty_field_counts": html_empty_field_counts,
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
        module_bulk_capabilities: dict[str, bool] | None = None,
        pending_saves: list[tuple[str, dict[str, Any]]] | None = None,
        previous_snapshot: Any = _PREVIOUS_UNSET,
        discovered: dict[str, dict[str, object]] | None = None,
    ) -> dict[str, object]:
        course_id = course["id"]
        fields = {"course_id": course_id, "course_code": course["code"], "term": course["term"]}
        course, session, moodle_id = self._source(user_id, course_id, now, discovered=discovered)
        discovered_entry = discovered.get(course_id) if discovered is not None else None
        index = self._activity_index(course, session, moodle_id, discovered_entry)
        entries = cast(list[dict[str, Any]], index["activities"])
        activities: list[dict[str, Any] | None] = [None] * len(entries)
        if previous_snapshot is _PREVIOUS_UNSET:
            previous = _load_previous_snapshot(snapshots, course_id, course["term"])
        else:
            previous = _validate_previous(previous_snapshot, course["term"])
        previous_by_source = _snapshot_by_source(previous)
        fallback_by_kind: dict[str, int] = {}
        fallback_reasons: dict[str, int] = {}
        incremental_supported = callable(getattr(self._client, "activity_updates_since", None))
        # A force sync is an explicit request to refresh activity details. It
        # must not spend the activity stage probing every Moodle course with
        # ``updates_since`` only to reuse the same snapshot afterwards.
        # Incremental probes remain the fast path for ordinary refreshes;
        # force runs go directly through the structured bulk path.
        reuse_allowed = incremental_supported and previous is not None and not self._force
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
                    update_course_ids = sorted(set(course_by_position.values()))

                    def fetch_updates(moodle_course_id: int) -> tuple[int, set[int]]:
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
                        return moodle_course_id, changed_ids

                    if self._update_workers == 1 or len(update_course_ids) <= 1:
                        update_results = [
                            fetch_updates(course_id) for course_id in update_course_ids
                        ]
                    else:
                        with ThreadPoolExecutor(
                            max_workers=min(self._update_workers, len(update_course_ids)),
                            thread_name_prefix="moodle-activity-updates",
                        ) as pool:
                            update_futures = [
                                pool.submit(fetch_updates, course_id)
                                for course_id in update_course_ids
                            ]
                            update_results = [future.result() for future in update_futures]
                    updates_checked += len(update_results)
                    changed_by_course.update(update_results)
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
        html_skipped = 0
        html_positions = set(changed_positions)
        html_fallback_reasons: dict[int, str] = {
            position: "no_structured_detail" for position in changed_positions
        }
        html_quality_counts: dict[str, int] = {}
        html_empty_field_counts: dict[str, int] = {}
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
                                reason = "activity_missing_from_bulk_response"
                                html_fallback_reasons[position] = reason
                                _count_fallback(
                                    fallback_by_kind, fallback_reasons, str(entry["kind"]), reason
                                )
                                _emit(
                                    self._telemetry,
                                    "moodle_activity_bulk_detail_fallback",
                                    {
                                        **fields,
                                        "source_id": entry["source_id"],
                                        "kind": entry["kind"],
                                        "reason": reason,
                                        "missing_fields": ["activity"],
                                    },
                                )
                                continue
                            if _bulk_detail_needs_html_fallback(detail):
                                bulk_fallbacks += 1
                                reason = "missing_bulk_fields"
                                html_fallback_reasons[position] = reason
                                _count_fallback(
                                    fallback_by_kind, fallback_reasons, str(entry["kind"]), reason
                                )
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
                                        "reason": reason,
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
                    for position in html_positions:
                        html_fallback_reasons[position] = "bulk_unavailable"
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
            for position in changed_positions:
                html_fallback_reasons[position] = "bulk_skipped_incomplete"
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
                    capability_known_unsupported = (
                        module_bulk_capabilities is not None
                        and module_bulk_capabilities.get(kind) is False
                    )
                    if capability_known_unsupported:
                        for position in positions:
                            html_fallback_reasons[position] = "module_bulk_unsupported"
                        _emit(
                            self._telemetry,
                            "moodle_activity_module_bulk_skipped",
                            {
                                **fields,
                                "moodle_course_id": moodle_course_id,
                                "kind": kind,
                                "reason": "unsupported_for_sync",
                                "activity_count": len(positions),
                            },
                        )
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
                        for position in positions:
                            html_fallback_reasons[position] = "module_bulk_unavailable"
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
                    module_bulk_successes = 0
                    module_bulk_fallback_reasons: list[str] = []
                    module_bulk_partial_details: dict[int, dict[str, Any]] = {}
                    for position in positions:
                        entry = entries[position]
                        detail = module_details.get(str(entry["source_id"]))
                        if not isinstance(detail, dict) or _bulk_detail_needs_html_fallback(detail):
                            reason = (
                                "activity_missing_from_module_bulk_response"
                                if not isinstance(detail, dict)
                                else "missing_module_bulk_fields"
                            )
                            html_fallback_reasons[position] = reason
                            module_bulk_fallback_reasons.append(reason)
                            if isinstance(detail, dict):
                                # Keep fields that the structured response did
                                # provide while the HTML request fills gaps.
                                activities[position] = {
                                    **entry,
                                    **_clean_bulk_detail(detail),
                                    "files": [],
                                    "term": course["term"],
                                }
                                module_bulk_partial_details[position] = detail
                            _count_fallback(fallback_by_kind, fallback_reasons, str(kind), reason)
                            _emit(
                                self._telemetry,
                                "moodle_activity_module_bulk_detail_fallback",
                                {
                                    **fields,
                                    "source_id": entry["source_id"],
                                    "kind": kind,
                                    "reason": reason,
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
                        module_bulk_successes += 1
                        bulk_submission_unknown += int(
                            clean_detail.get("submission_state") == "unknown"
                        )
                    # UFMG's type-specific endpoint can return a complete
                    # activity map while omitting both optional fields for
                    # every item.  In that case HTML is not an enrichment
                    # source (the production run proved it returns the same
                    # empty values), so avoid the N+1 page crawl.  Missing
                    # module IDs and transport/shape failures still retain
                    # the real HTML fallback below.
                    if (
                        module_bulk_successes == 0
                        and len(module_bulk_fallback_reasons) == len(positions)
                        and module_bulk_fallback_reasons
                        and kind == "quiz"
                        and all(
                            reason == "missing_module_bulk_fields"
                            for reason in module_bulk_fallback_reasons
                        )
                        and all(
                            _module_detail_is_empty(module_bulk_partial_details[position])
                            for position in positions
                            if position in module_bulk_partial_details
                        )
                        and len(module_bulk_partial_details) == len(positions)
                    ):
                        for position in positions:
                            # The structured response was already copied into
                            # ``activities`` above. Keep it intact: quiz dates
                            # remain useful when optional HTML enrichment is
                            # empty, and must not be reset to index-only data.
                            html_positions.discard(position)
                        html_skipped += len(positions)
                        _emit(
                            self._telemetry,
                            "moodle_activity_html_fallback_skipped",
                            {
                                **fields,
                                "moodle_course_id": moodle_course_id,
                                "kind": kind,
                                "reason": "module_bulk_empty_optional_fields",
                                "activity_count": len(positions),
                            },
                        )
                    # An empty optional payload is a valid response for this
                    # course, not evidence that the endpoint is unsupported
                    # for every other course.  Cache only a transport/shape
                    # failure; otherwise one empty course would force HTML
                    # fallbacks for every later course.
                    if (
                        module_bulk_capabilities is not None
                        and module_bulk_successes == 0
                        and any(
                            reason
                            in {
                                "activity_missing_from_module_bulk_response",
                                "module_bulk_unavailable",
                            }
                            for reason in module_bulk_fallback_reasons
                        )
                    ):
                        module_bulk_capabilities[kind] = False

        def capture_activity(
            position: int, entry: dict[str, Any]
        ) -> tuple[dict[str, object] | None, dict[str, object]]:
            """Fetch one HTML detail and return failure plus quality evidence."""

            started = monotonic()
            fallback_reason = html_fallback_reasons.get(position, "no_structured_detail")
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
                if not isinstance(detail, dict):
                    raise InvalidMoodleResponse("activity_page_shape")
                quality = _html_detail_quality(detail)
                quality.update(
                    {
                        "source_id": entry["source_id"],
                        "kind": entry["kind"],
                        "fallback_reason": fallback_reason,
                        "duration_ms": round((monotonic() - started) * 1000),
                    }
                )
                _emit(
                    self._telemetry,
                    "moodle_activity_html_detail_result",
                    {**fields, **quality},
                )
                activities[position] = {
                    **entry,
                    **_merge_activity_details(
                        activities[position] or {}, _clean_activity_detail(detail)
                    ),
                    "files": [],
                    "term": course["term"],
                }
                return None, quality
            except Exception as error:
                upstream_class, upstream_status = _classify_upstream(error)
                reason = (
                    error.reason
                    if isinstance(error, InvalidMoodleResponse)
                    else type(error).__name__
                )
                duration_ms = round((monotonic() - started) * 1000)
                failure: dict[str, object] = {
                    **fields,
                    "source_id": entry["source_id"],
                    "kind": entry["kind"],
                    "reason": reason,
                    "exception_type": type(error).__name__,
                    "upstream_class": upstream_class,
                    "duration_ms": duration_ms,
                    "attempt": 1,
                }
                if upstream_status is not None:
                    failure["upstream_status"] = upstream_status
                _emit(self._telemetry, "activity_snapshot_activity_failed", failure)
                response_details = (
                    error.details if isinstance(error, InvalidMoodleResponse) else {}
                )
                response_status = response_details.get("response_status")
                if type(response_status) is not int or not 100 <= response_status <= 599:
                    response_status = upstream_status
                response_bytes = response_details.get("response_bytes")
                if type(response_bytes) is not int or response_bytes < 0:
                    response_bytes = 0
                quality = {
                    **fields,
                    "source_id": entry["source_id"],
                    "kind": entry["kind"],
                    "fallback_reason": fallback_reason,
                    "response_status": response_status,
                    "response_bytes": response_bytes,
                    "description_chars": 0,
                    "attachment_count": 0,
                    "empty_fields": [],
                    "outcome": "failed",
                    "metadata_source": "error",
                    "duration_ms": duration_ms,
                    "error_reason": reason,
                    "upstream_class": upstream_class,
                }
                _emit(self._telemetry, "moodle_activity_html_detail_result", quality)
                return failure, quality

        outcomes: list[tuple[dict[str, object] | None, dict[str, object]]] = []
        if html_positions:
            # Bounded pool: every unresolved activity is attempted even when
            # another one fails, while the final snapshot remains index-ordered.
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                futures = [
                    pool.submit(capture_activity, position, entries[position])
                    for position in sorted(html_positions)
                ]
                outcomes = [future.result() for future in futures]
        failures = [failure for failure, _quality in outcomes if failure is not None]
        for _failure, quality in outcomes:
            outcome = str(quality.get("outcome", "failed"))
            html_quality_counts[outcome] = html_quality_counts.get(outcome, 0) + 1
            for field in cast(list[str], quality["empty_fields"]):
                html_empty_field_counts[field] = html_empty_field_counts.get(field, 0) + 1
        if failures:
            raise ActivitySnapshotCaptureFailed(
                failed_count=len(failures),
                first_reason=str(failures[0]["reason"]),
                metrics={
                    "html_quality_counts": html_quality_counts,
                    "html_empty_field_counts": html_empty_field_counts,
                },
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
                "html_skipped_count": html_skipped,
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
            "html_skipped_count": html_skipped,
            "module_bulk_count": module_bulk_count,
            "module_bulk_calls": module_bulk_calls,
            "module_bulk_failures": module_bulk_failures,
            "updates_checked": updates_checked,
            "updates_changed": updates_changed,
            "fallback_by_kind": fallback_by_kind,
            "fallback_reasons": fallback_reasons,
            "html_quality_counts": html_quality_counts,
            "html_empty_field_counts": html_empty_field_counts,
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
        return self._activity_index(course, session, moodle_id)

    def _activity_index(
        self,
        course: dict[str, Any],
        session: UFMGSession,
        moodle_id: int,
        discovered_entry: dict[str, object] | None = None,
    ) -> dict[str, object]:
        course_id = course["id"]

        shared_candidates = (
            discovered_entry.get("activity_candidates")
            if isinstance(discovered_entry, dict)
            else None
        )
        if isinstance(shared_candidates, list) and all(
            isinstance(candidate, dict) for candidate in shared_candidates
        ):
            entries = cast(list[dict[str, object]], shared_candidates)
            _emit(
                self._telemetry,
                "moodle_activity_index_reused",
                {
                    "course_id": course_id,
                    "course_code": course["code"],
                    "moodle_course_id": moodle_id,
                    "activity_count": len(entries),
                    "source": "shared_course_discovery",
                },
            )
            timed_stage(
                "course_activity_index",
                lambda: None,
                telemetry=self._telemetry,
                fields={
                    "course_id": course_id,
                    "course_code": course["code"],
                    "moodle_course_id": moodle_id,
                    "cache_hit": True,
                    "activity_count": len(entries),
                },
            )
            return {
                "activities": entries,
                "course_id": course_id,
                "term": course["term"],
                "moodle_course_id": str(moodle_id),
            }

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
