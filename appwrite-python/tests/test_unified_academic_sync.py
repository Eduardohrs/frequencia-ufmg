from unified_academic_sync import UnifiedAcademicSyncService


def _course(
    code: str = "ELE028",
    *,
    candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "course_id": code.lower(),
        "course_code": code,
        "term": "2026-2",
        "candidates": candidates
        if candidates is not None
        else [
            {
                "source_id": "101",
                "kind": "link",
                "relevance": "teaching_plan",
                "origin": "canonical",
            }
        ],
    }


class _Siga:
    def __init__(self) -> None:
        self.calls = 0

    def sync_siga(self, user_id: str, *, now: int) -> dict[str, object]:
        assert (user_id, now) == ("user", 42)
        self.calls += 1
        return {"courses": {"created": 1}, "schedules": {"updated": 1}}


class _Moodle:
    def __init__(self, courses: list[dict[str, object]]) -> None:
        self.courses = courses
        self.calls = 0

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        assert (user_id, now) == ("user", 42)
        self.calls += 1
        return {
            "dates": {"created": 2},
            "content": {"courses": self.courses, "candidate_total": 3},
            "capabilities": {"direct_download_supported": True},
        }


class _Plans:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int, int]] = []

    def import_plan(
        self,
        user_id: str,
        *,
        course_id: str,
        term: str,
        source_id: int,
        now: int,
    ) -> dict[str, object]:
        self.calls.append((user_id, course_id, term, source_id, now))
        return {"plan": "created"}


class _Reconciler:
    def __init__(self, previews: dict[str, dict[str, object]]) -> None:
        self.previews = previews
        self.calls: list[tuple[str, bool]] = []

    def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
        self.calls.append((course_id, apply))
        preview = self.previews[course_id]
        return {**preview, "applied": len(preview["changes"]) if apply else 0}


def _preview(
    *,
    changes: list[dict[str, object]] | None = None,
    conflicting: int = 0,
    assessment_conflicts: int = 0,
) -> dict[str, object]:
    return {
        "changes": changes or [],
        "conflicting": conflicting,
        "assessment_conflicts": assessment_conflicts,
    }


def test_sync_applies_only_unambiguous_changes_and_returns_a_bounded_summary() -> None:
    courses = [_course(), _course("MAT001"), _course("ENG002")]
    siga = _Siga()
    moodle = _Moodle(courses)
    plans = _Plans()
    reconciler = _Reconciler(
        {
            "ele028": _preview(changes=[{"action": "create_session"}]),
            "mat001": _preview(),
            "eng002": _preview(
                changes=[{"action": "create_session"}], conflicting=1
            ),
        }
    )

    result = UnifiedAcademicSyncService(siga, moodle, plans, reconciler).sync(
        "user", now=42
    )

    assert siga.calls == moodle.calls == 1
    assert len(plans.calls) == 3
    assert reconciler.calls == [
        ("ele028", False),
        ("ele028", True),
        ("mat001", False),
        ("eng002", False),
    ]
    assert result["teaching_plans"] == {
        "available": 3,
        "imported": 3,
        "applied": 1,
        "unchanged": 1,
        "review_required": 1,
    }
    assert result["exceptions"] == [
        {
            "course_id": "eng002",
            "course_code": "ENG002",
            "reason": "reconciliation_conflict",
            "candidate_count": 1,
            "changes": [{"action": "create_session"}],
            "conflicting": 1,
            "assessment_conflicts": 0,
        }
    ]
    assert result["moodle"] == {
        "dates": {"created": 2},
        "content": {"candidate_total": 3},
        "capabilities": {"direct_download_supported": True},
    }


def test_sync_ignores_metaturma_and_reports_multiple_canonical_plans() -> None:
    plan = {
        "source_id": "101",
        "kind": "link",
        "relevance": "teaching_plan",
        "origin": "canonical",
    }
    courses = [
        _course(
            candidates=[
                plan,
                {**plan, "source_id": "102", "origin": "metaturma"},
            ]
        ),
        _course(
            "MAT001",
            candidates=[plan, {**plan, "source_id": "103"}],
        ),
    ]
    plans = _Plans()
    reconciler = _Reconciler({"ele028": _preview()})

    result = UnifiedAcademicSyncService(
        _Siga(), _Moodle(courses), plans, reconciler
    ).sync("user", now=42)

    assert [call[1] for call in plans.calls] == ["ele028"]
    assert result["teaching_plans"] == {
        "available": 2,
        "imported": 1,
        "applied": 0,
        "unchanged": 1,
        "review_required": 1,
    }
    assert result["exceptions"] == [
        {
            "course_id": "mat001",
            "course_code": "MAT001",
            "reason": "ambiguous_teaching_plan",
            "candidate_count": 2,
            "changes": [],
            "conflicting": 0,
            "assessment_conflicts": 0,
        }
    ]


def test_sync_ignores_courses_without_a_canonical_teaching_plan() -> None:
    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course(candidates=[])]),
        _Plans(),
        _Reconciler({}),
    ).sync("user", now=42)

    assert result["teaching_plans"] == {
        "available": 0,
        "imported": 0,
        "applied": 0,
        "unchanged": 0,
        "review_required": 0,
    }


def test_sync_rejects_more_exceptions_than_the_bounded_contract() -> None:
    plan = {
        "source_id": "101",
        "kind": "link",
        "relevance": "teaching_plan",
        "origin": "canonical",
    }
    courses = [
        _course(f"MAT{index:03}", candidates=[plan, {**plan, "source_id": "102"}])
        for index in range(51)
    ]

    try:
        UnifiedAcademicSyncService(
            _Siga(), _Moodle(courses), _Plans(), _Reconciler({})
        ).sync("user", now=42)
    except ValueError as error:
        assert str(error) == "too many academic sync exceptions"
    else:
        raise AssertionError("the bounded exception contract must be enforced")
