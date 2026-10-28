"""Persist source-specific sync decisions without discarding the last complete copy."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from firestore_rest import FirestoreNotFound, FirestoreRestClient
from sync_timing import Telemetry, _emit

_PLAN_FIELDS = {"criteria", "schedule", "assessment_dates"}


class SyncDeferred(Exception):
    """This source is intentionally not queried yet; no replacement copy exists."""


class CourseSyncPolicy:
    def __init__(self, store: FirestoreRestClient, *, telemetry: Telemetry | None = None) -> None:
        self.store, self.telemetry = store, telemetry

    def state(self, course_id: str, source: str) -> dict[str, Any]:
        if source not in {"plan", "activities", "planPreference"}:
            raise ValueError("invalid sync source")
        try:
            doc = self.store.get_user_document("courses", course_id, "syncState", source)
        except FirestoreNotFound:
            return {}
        return dict(json.loads(doc["fields"]["stateJson"]["stringValue"]))

    def _save(self, course_id: str, source: str, state: dict[str, Any]) -> None:
        try:
            self.store.patch_user_document(
                "courses",
                course_id,
                "syncState",
                source,
                fields={"stateJson": {"stringValue": json.dumps(state, separators=(",", ":"))}},
            )
        except Exception as error:
            _emit(
                self.telemetry,
                "course_sync_policy_persistence_failed",
                {"course_id": course_id, "source": source, "reason": type(error).__name__},
            )
            raise

    def confirm_plan(
        self, course_id: str, *, now: int, term: str = "", paused: bool = True
    ) -> None:
        # User preference is isolated from in-flight automatic writes.
        self._save(course_id, "planPreference", {"manual_confirmed": paused, "source_key": term})
        _emit(
            self.telemetry,
            "course_sync_manual_policy_changed",
            {"course_id": course_id, "source": "plan", "manual_confirmed": paused},
        )

    def manual_paused(self, course_id: str, term: str) -> bool:
        preference = self.state(course_id, "planPreference")
        return preference.get("manual_confirmed") is True and preference.get("source_key") in (
            "",
            term,
        )

    def run(
        self,
        course_id: str,
        source: str,
        key: str,
        *,
        now: int,
        fetch: Callable[[], dict[str, object]],
        force: bool = False,
        created_at: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        state = self.state(course_id, source)
        paused = self.manual_paused(course_id, key.split(":")[0]) if source == "plan" else False
        old_key = state.get("source_key")
        if old_key != key:
            state = {}
        state.setdefault("first_seen_at", min(now, created_at) if created_at is not None else now)
        state["source_key"] = key
        complete = set(state.get("complete_fields", []))
        reason = ""
        if not force:
            if paused:
                reason = "manual_confirmed"
            elif source == "plan" and complete >= _PLAN_FIELDS:
                reason = "complete"
            elif (
                source == "plan"
                and "last_attempt_at" in state
                and now - state["first_seen_at"] >= 30 * 86400
            ):
                reason = "search_window_closed"
            elif now < state.get("next_due_at", 0):
                reason = "failure_backoff" if state.get("failures", 0) else "recent_snapshot"
        context = {
            "course_id": course_id,
            "source": source,
            "source_key": key,
            "complete_fields": sorted(complete),
            "missing_fields": sorted(_PLAN_FIELDS - complete) if source == "plan" else [],
            "next_due_at": state.get("next_due_at", now),
        }
        if reason:
            _emit(
                self.telemetry,
                "course_sync_skipped",
                {
                    **context,
                    "reason": reason,
                    "retained_previous": True,
                    "reused_snapshot_payload_bytes": (state.get("result") or {}).get(
                        "snapshot_payload_bytes"
                    ),
                },
            )
            if state.get("result") is None:
                raise SyncDeferred(reason)
            return dict(state["result"]), True
        _emit(
            self.telemetry,
            "course_sync_selected",
            {**context, "reason": "explicit_refresh" if force else "due"},
        )
        try:
            result = fetch()
        except Exception as error:
            failures = int(state.get("failures", 0)) + 1
            state.update(
                failures=failures,
                last_attempt_at=now,
                next_due_at=now + min(86400, 900 * 2 ** min(failures - 1, 7)),
            )
            _emit(
                self.telemetry,
                "course_sync_attempt_failed",
                {
                    **context,
                    "reason": type(error).__name__,
                    "attempt": failures,
                    "next_due_at": state["next_due_at"],
                    "retained_previous": True,
                },
            )
            self._save(course_id, source, state)
            raise
        complete = set()
        if source == "plan":
            if result.get("criteria_total", 0):
                complete.add("criteria")
            if result.get("schedule_total", 0):
                complete.add("schedule")
            if result.get("assessment_total", 0) and result.get("undated_assessment_total", 0) == 0:
                complete.add("assessment_dates")
        state.update(
            result=result,
            complete_fields=sorted(complete),
            failures=0,
            last_attempt_at=now,
            next_due_at=now + (21600 if source == "activities" else 86400),
        )
        self._save(course_id, source, state)
        _emit(
            self.telemetry,
            "course_sync_source_updated",
            {
                **context,
                "complete_fields": sorted(complete),
                "missing_fields": sorted(_PLAN_FIELDS - complete) if source == "plan" else [],
                "next_due_at": state["next_due_at"],
            },
        )
        return result, False


class AdaptiveTeachingPlanImporter:
    def __init__(
        self,
        importer: Any,
        policy: CourseSyncPolicy,
        *,
        force: bool = False,
        created_at: Callable[[str], str | None] | None = None,
    ) -> None:
        self.importer, self.policy, self.force = importer, policy, force
        self.created_at = created_at

    def import_plan(
        self, user_id: str, *, course_id: str, term: str, source_id: int, now: int
    ) -> dict[str, object]:
        created = self.created_at(course_id) if self.created_at is not None else None
        created_at = int(datetime.fromisoformat(created).timestamp()) if created else None
        try:
            result, _ = self.policy.run(
                course_id,
                "plan",
                f"{term}:{source_id}",
                now=now,
                fetch=lambda: self.importer.import_plan(
                    user_id, course_id=course_id, term=term, source_id=source_id, now=now
                ),
                force=self.force,
                created_at=created_at,
            )
            return result
        except SyncDeferred as error:
            return {"plan": "deferred" if str(error) == "manual_confirmed" else "unavailable"}
