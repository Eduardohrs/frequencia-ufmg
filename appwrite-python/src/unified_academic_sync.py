"""Orchestrate one bounded academic sync and surface only reviewable exceptions."""

from typing import Protocol, cast


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
    ) -> None:
        self._siga = siga
        self._moodle = moodle
        self._plans = plans
        self._reconciler = reconciler

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        siga = self._siga.sync_siga(user_id, now=now)
        moodle = self._moodle.sync(user_id, now=now)
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
                exceptions.append(
                    _exception(course, "ambiguous_teaching_plan", len(candidates))
                )
                continue

            source_id = int(cast(str, candidates[0]["source_id"]))
            course_id = cast(str, course["course_id"])
            self._plans.import_plan(
                user_id,
                course_id=course_id,
                term=cast(str, course["term"]),
                source_id=source_id,
                now=now,
            )
            summary["imported"] += 1
            preview = self._reconciler.reconcile(course_id, apply=False)
            if _requires_review(preview):
                summary["review_required"] += 1
                exceptions.append(_reconciliation_exception(course, preview))
                continue
            changes = cast(list[object], preview["changes"])
            if not changes:
                summary["unchanged"] += 1
                continue
            applied = self._reconciler.reconcile(course_id, apply=True)
            summary["applied"] += cast(int, applied["applied"])

        if len(exceptions) > 50:
            raise ValueError("too many academic sync exceptions")
        return {
            "siga": siga,
            "moodle": {
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
    return (
        cast(int, preview["conflicting"]) > 0
        or cast(int, preview["assessment_conflicts"]) > 0
    )


def _exception(
    course: dict[str, object], reason: str, candidate_count: int
) -> dict[str, object]:
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
