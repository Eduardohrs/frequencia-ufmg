"""Orchestrate one bounded academic sync and surface only reviewable exceptions."""

from collections.abc import Callable, Mapping
from functools import partial
from time import monotonic
from typing import Protocol, cast

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
    ) -> None:
        self._siga = siga
        self._moodle = moodle
        self._plans = plans
        self._reconciler = reconciler
        self._telemetry = telemetry
        self._monotonic = monotonic

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
        for course in courses:
            candidates = _canonical_teaching_plans(course)
            if not candidates:
                continue
            summary["available"] += 1
            if len(candidates) != 1:
                summary["review_required"] += 1
                exceptions.append(_exception(course, "ambiguous_teaching_plan", len(candidates)))
                continue

            source_id = int(cast(str, candidates[0]["source_id"]))
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
            except _FATAL_FAILURES:
                raise
            except Exception as error:
                summary["review_required"] += 1
                exceptions.append(_unavailable_exception(course))
                self._record_course_failure(
                    course,
                    source_id=source_id,
                    stage="teaching_plan_import",
                    error=error,
                )
                continue
            if imported_plan.get("plan") == "unavailable":
                summary["review_required"] += 1
                exceptions.append(_unavailable_exception(course))
                continue
            if imported_plan.get("plan") == "deferred":
                summary["unchanged"] += 1
                continue
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
                continue
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
                    course,
                    source_id=source_id,
                    stage="teaching_plan_reconciliation",
                    error=error,
                )
                continue
            if _requires_review(preview):
                summary["review_required"] += 1
                exceptions.append(_reconciliation_exception(course, preview))
                continue
            changes = cast(list[object], preview["changes"])
            if not changes:
                summary["unchanged"] += 1
                continue
            try:
                applied = self._timed(
                    "teaching_plan_apply",
                    partial(self._reconciler.reconcile, course_id, apply=True),
                    course=course,
                )
            except _FATAL_FAILURES:
                raise
            except Exception as error:
                summary["review_required"] += 1
                exceptions.append(_unavailable_exception(course))
                self._record_course_failure(
                    course,
                    source_id=source_id,
                    stage="teaching_plan_apply",
                    error=error,
                )
                continue
            summary["applied"] += cast(int, applied["applied"])

        if len(exceptions) > 50:
            raise ValueError("too many academic sync exceptions")
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
