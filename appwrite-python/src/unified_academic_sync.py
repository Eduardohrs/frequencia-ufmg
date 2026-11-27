"""Orchestrate one bounded academic sync and surface only reviewable exceptions."""

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from time import monotonic
from typing import Protocol, cast

from academic_sync_lineage import DIARIO_TEACHING_PLAN
from firestore_rest import FirestoreAccessDenied, FirestoreUnavailable
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable
from ufmg_session_store import (
    UFMGReauthenticationRequired,
    UFMGSessionStoreUnavailable,
)

Telemetry = Callable[[str, Mapping[str, object]], None]
_FATAL_FAILURES = (
    FirestoreAccessDenied,
    FirestoreUnavailable,
    MoodleTokenStoreUnavailable,
    MoodleUnavailable,
    UFMGReauthenticationRequired,
    UFMGSessionStoreUnavailable,
)


class _SigaSync(Protocol):
    def sync_siga(self, user_id: str, *, now: int) -> dict[str, object]: ...


class _MoodleSync(Protocol):
    def sync(self, user_id: str, *, now: int) -> dict[str, object]: ...


class _PlanImporter(Protocol):
    def import_plan(
        self,
        user_id: str,
        *,
        course_id: str,
        term: str,
        source_id: int,
        now: int,
    ) -> dict[str, object]: ...


class _PlanReconciler(Protocol):
    def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]: ...


class UnifiedAcademicSyncService:
    """Synchronize known sources and apply only unambiguous plan changes."""

    def __init__(
        self,
        siga: _SigaSync,
        moodle: _MoodleSync,
        plans: _PlanImporter,
        reconciler: _PlanReconciler,
        *,
        telemetry: Telemetry | None = None,
        monotonic: Callable[[], float] = monotonic,
        plan_workers: int = 1,
    ) -> None:
        self._siga = siga
        self._moodle = moodle
        self._plans = plans
        self._reconciler = reconciler
        self._telemetry = telemetry
        self._monotonic = monotonic
        if not 1 <= plan_workers <= 8:
            raise ValueError("invalid teaching plan concurrency")
        self._plan_workers = plan_workers

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        siga = self._timed("siga", lambda: self._siga.sync_siga(user_id, now=now))
        moodle = self._timed("moodle", lambda: self._moodle.sync(user_id, now=now))
        content = cast(dict[str, object], moodle["content"])
        courses = cast(list[dict[str, object]], content["courses"])

        summary = {
            "available": 0,
            "imported": 0,
            "applied": 0,
            "unchanged": 0,
            "review_required": 0,
        }
        exceptions: list[dict[str, object]] = []
        pending: list[tuple[dict[str, object], int]] = []
        for course in courses:
            candidates = _canonical_teaching_plans(course)
            if not candidates:
                continue
            summary["available"] += 1
            if len(candidates) != 1:
                summary["review_required"] += 1
                exceptions.append(_exception(course, "ambiguous_teaching_plan", len(candidates)))
                continue
            pending.append((course, int(cast(str, candidates[0]["source_id"]))))

        # Plans are independent after content discovery.  Keep the default
        # serial mode for embedders/tests, while production opts into a small
        # bounded pool so one slow Diário report cannot hold every other plan.
        with ThreadPoolExecutor(
            max_workers=self._plan_workers, thread_name_prefix="plan-sync"
        ) as pool:
            futures = [
                pool.submit(self._sync_one_plan, user_id, course, source_id, now)
                for course, source_id in pending
            ]
            for future in futures:
                outcome = future.result()
                outcome_summary = cast(dict[str, int], outcome["summary"])
                for key in ("available", "imported", "applied", "unchanged", "review_required"):
                    summary[key] += outcome_summary[key]
                exceptions.extend(cast(list[dict[str, object]], outcome["exceptions"]))

        if len(exceptions) > 50:
            raise ValueError("too many academic sync exceptions")
        self._emit(
            "academic_sync_lineage",
            {
                **DIARIO_TEACHING_PLAN,
                "source": "teaching_plan",
                "dataset": "assessments_and_schedule",
                "consumer": "course_dates_and_teaching_plan_view",
                "courses_considered": summary["available"],
                "plans_imported": summary["imported"],
                "changes_applied": summary["applied"],
                "unchanged": summary["unchanged"],
                "review_required": summary["review_required"],
                "overlap_policy": "plan_assessments_reconcile_into_course_dates",
            },
        )
        if self._plan_workers > 1:
            self._emit(
                "sync_span_graph",
                {
                    "root": "academic_sync",
                    "nodes": [
                        {"name": "siga", "depends_on": [], "parallel_group": None},
                        {"name": "moodle", "depends_on": ["siga"], "parallel_group": None},
                        {
                            "name": "teaching_plan_import",
                            "depends_on": ["moodle"],
                            "parallel_group": "teaching_plans",
                        },
                        {
                            "name": "teaching_plan_reconciliation",
                            "depends_on": ["teaching_plan_import"],
                            "parallel_group": "teaching_plans",
                        },
                        {
                            "name": "teaching_plan_apply",
                            "depends_on": ["teaching_plan_reconciliation"],
                            "parallel_group": "teaching_plans",
                        },
                    ],
                    "join": "academic_sync_result",
                },
            )
        return {
            "siga": siga,
            "moodle": {
                **({"activities": moodle["activities"]} if "activities" in moodle else {}),
                "dates": moodle["dates"],
                "content": {
                    key: value
                    for key, value in content.items()
                    if key not in {"courses", "catalog"}
                },
                "capabilities": moodle["capabilities"],
            },
            "teaching_plans": summary,
            "exceptions": exceptions,
        }

    def _sync_one_plan(
        self,
        user_id: str,
        course: dict[str, object],
        source_id: int,
        now: int,
    ) -> dict[str, object]:
        summary = {
            "available": 0,
            "imported": 0,
            "applied": 0,
            "unchanged": 0,
            "review_required": 0,
        }
        exceptions: list[dict[str, object]] = []
        course_id = cast(str, course["course_id"])
        term = cast(str, course["term"])
        try:
            imported_plan = self._timed(
                "teaching_plan_import",
                partial(
                    self._plans.import_plan,
                    user_id,
                    course_id=course_id,
                    term=term,
                    source_id=source_id,
                    now=now,
                ),
                course=course,
            )
        except MoodleUnavailable as error:
            # An HTTP 5xx for one Diário plan is a course-level failure, not
            # proof that the already completed SIGA/Moodle work failed.
            if error.upstream_status is None or error.upstream_status < 500:
                raise
            summary["review_required"] += 1
            exceptions.append(_unavailable_exception(course))
            self._record_course_failure(
                course, source_id=source_id, stage="teaching_plan_import", error=error
            )
            return {"summary": summary, "exceptions": exceptions}
        except _FATAL_FAILURES:
            raise
        except Exception as error:
            summary["review_required"] += 1
            exceptions.append(_unavailable_exception(course))
            self._record_course_failure(
                course, source_id=source_id, stage="teaching_plan_import", error=error
            )
            return {"summary": summary, "exceptions": exceptions}
        if imported_plan.get("plan") == "unavailable":
            summary["review_required"] += 1
            exceptions.append(_unavailable_exception(course))
            return {"summary": summary, "exceptions": exceptions}
        if imported_plan.get("plan") == "deferred":
            summary["unchanged"] += 1
            return {"summary": summary, "exceptions": exceptions}
        if imported_plan.get("plan") == "not_published":
            summary["review_required"] += 1
            exceptions.append(_exception(course, "teaching_plan_not_published", 1))
            self._emit(
                "academic_sync_plan_not_published",
                {
                    "course_id": course_id,
                    "course_code": course["course_code"],
                    "term": term,
                    "source_id": source_id,
                    "reason": "explicitly_not_published",
                    "preserved_existing_data": True,
                },
            )
            return {"summary": summary, "exceptions": exceptions}
        summary["imported"] += 1
        try:
            preview = self._timed(
                "teaching_plan_reconciliation",
                partial(self._reconciler.reconcile, course_id, apply=False),
                course=course,
            )
        except _FATAL_FAILURES:
            raise
        except Exception as error:
            summary["review_required"] += 1
            exceptions.append(_unavailable_exception(course))
            self._record_course_failure(
                course, source_id=source_id, stage="teaching_plan_reconciliation", error=error
            )
            return {"summary": summary, "exceptions": exceptions}
        if _requires_review(preview):
            summary["review_required"] += 1
            exceptions.append(_reconciliation_exception(course, preview))
            return {"summary": summary, "exceptions": exceptions}
        excluded_occurrences = cast(list[object], preview.get("excluded", []))
        exclusion_exception: dict[str, object] | None = None
        if excluded_occurrences:
            summary["review_required"] += 1
            exclusion_exception = _reconciliation_exclusion_exception(course, preview)
            exceptions.append(exclusion_exception)
        if not cast(list[object], preview["changes"]):
            if not excluded_occurrences:
                summary["unchanged"] += 1
            if exclusion_exception is not None:
                self._emit_exclusion_result(
                    course,
                    excluded_occurrences,
                    safe_changes_count=0,
                    apply_status="not_needed",
                )
            return {"summary": summary, "exceptions": exceptions}
        try:
            applied = self._timed(
                "teaching_plan_apply",
                partial(self._reconciler.reconcile, course_id, apply=True),
                course=course,
            )
        except _FATAL_FAILURES:
            raise
        except Exception as error:
            if exclusion_exception is not None:
                # This course already has one review exception. Keep its
                # exclusions and attach the failed apply outcome instead of
                # counting the same course twice in the result contract.
                exclusion_exception["apply_error"] = type(error).__name__
                self._emit_exclusion_result(
                    course,
                    excluded_occurrences,
                    safe_changes_count=len(cast(list[object], preview["changes"])),
                    apply_status="failed",
                    apply_error=type(error).__name__,
                )
            else:
                summary["review_required"] += 1
                exceptions.append(_unavailable_exception(course))
            self._record_course_failure(
                course, source_id=source_id, stage="teaching_plan_apply", error=error
            )
            return {"summary": summary, "exceptions": exceptions}
        summary["applied"] += cast(int, applied["applied"])
        if exclusion_exception is not None:
            self._emit_exclusion_result(
                course,
                excluded_occurrences,
                safe_changes_count=len(cast(list[object], preview["changes"])),
                apply_status="applied",
            )
        return {"summary": summary, "exceptions": exceptions}

    def _emit_exclusion_result(
        self,
        course: Mapping[str, object],
        excluded: list[object],
        *,
        safe_changes_count: int,
        apply_status: str,
        apply_error: str | None = None,
    ) -> None:
        fields: dict[str, object] = {
            "course_id": course["course_id"],
            "course_code": course["course_code"],
            "excluded_count": len(excluded),
            "excluded": excluded[:20],
            "safe_changes_count": safe_changes_count,
            "safe_changes_apply_status": apply_status,
            "safe_changes_still_applied": apply_status != "failed",
        }
        if apply_error is not None:
            fields["apply_error"] = apply_error
        self._emit("academic_sync_plan_occurrences_excluded", fields)

    def _timed(
        self,
        stage: str,
        action: Callable[[], dict[str, object]],
        *,
        course: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        started = self._monotonic()
        try:
            result = action()
        except Exception as error:
            self._record_stage(
                "academic_sync_stage_failed",
                stage,
                started,
                course=course,
                error=error,
            )
            raise
        self._record_stage("academic_sync_stage_completed", stage, started, course=course)
        return result

    def _record_stage(
        self,
        event: str,
        stage: str,
        started: float,
        *,
        course: Mapping[str, object] | None,
        error: Exception | None = None,
    ) -> None:
        if self._telemetry is None:
            return
        fields: dict[str, object] = {
            "stage": stage,
            "duration_ms": round((self._monotonic() - started) * 1_000, 3),
        }
        if course is not None:
            fields.update(course_id=course["course_id"], course_code=course["course_code"])
        if error is not None:
            fields["reason"] = (
                error.reason if isinstance(error, InvalidMoodleResponse) else type(error).__name__
            )
            fields["exception_type"] = type(error).__name__
        self._emit(event, fields)

    def _record_course_failure(
        self,
        course: Mapping[str, object],
        *,
        source_id: int,
        stage: str,
        error: Exception,
    ) -> None:
        if self._telemetry is None:
            return
        fields: dict[str, object] = {
            "course_id": course["course_id"],
            "course_code": course["course_code"],
            "term": course["term"],
            "source_id": source_id,
            "stage": stage,
            "reason": error.reason
            if isinstance(error, InvalidMoodleResponse)
            else type(error).__name__,
            "exception_type": type(error).__name__,
        }
        if isinstance(error, InvalidMoodleResponse):
            fields.update(error.details)
        if isinstance(error, MoodleUnavailable):
            fields["upstream_status"] = error.upstream_status
            fields["timed_out"] = error.timed_out
        self._emit("academic_sync_course_failed", fields)

    def _emit(self, event: str, fields: Mapping[str, object]) -> None:
        telemetry = cast(Telemetry, self._telemetry)
        try:
            telemetry(event, fields)
        except Exception:
            # A broken telemetry sink must not break the user's synchronization.
            return


def _canonical_teaching_plans(
    course: dict[str, object],
) -> list[dict[str, object]]:
    candidates = cast(list[dict[str, object]], course["candidates"])
    return [
        candidate
        for candidate in candidates
        if candidate.get("origin") == "canonical"
        and candidate.get("relevance") == "teaching_plan"
        and candidate.get("kind") == "link"
    ]


def _requires_review(preview: dict[str, object]) -> bool:
    return cast(int, preview["conflicting"]) > 0 or cast(int, preview["assessment_conflicts"]) > 0


def _exception(course: dict[str, object], reason: str, candidate_count: int) -> dict[str, object]:
    return {
        "course_id": course["course_id"],
        "course_code": course["course_code"],
        "reason": reason,
        "candidate_count": candidate_count,
        "changes": [],
        "conflicting": 0,
        "assessment_conflicts": 0,
    }


def _reconciliation_exception(
    course: dict[str, object], preview: dict[str, object]
) -> dict[str, object]:
    return {
        "course_id": course["course_id"],
        "course_code": course["course_code"],
        "reason": "reconciliation_conflict",
        "candidate_count": 1,
        "changes": cast(list[object], preview["changes"])[:20],
        "conflicting": preview["conflicting"],
        "assessment_conflicts": preview["assessment_conflicts"],
    }


def _reconciliation_exclusion_exception(
    course: dict[str, object], preview: dict[str, object]
) -> dict[str, object]:
    return {
        "course_id": course["course_id"],
        "course_code": course["course_code"],
        "reason": "teaching_plan_occurrences_not_representable",
        "candidate_count": 1,
        "changes": cast(list[object], preview["changes"])[:20],
        "excluded": cast(list[object], preview["excluded"])[:20],
        "conflicting": 0,
        "assessment_conflicts": 0,
    }


def _unavailable_exception(course: Mapping[str, object]) -> dict[str, object]:
    return {
        "course_id": course["course_id"],
        "course_code": course["course_code"],
        "reason": "teaching_plan_unavailable",
        "candidate_count": 1,
        "changes": [],
        "conflicting": 0,
        "assessment_conflicts": 0,
    }
