import pytest

from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
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
    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        self.calls: list[tuple[str, str, str, int, int]] = []
        self.failures = failures or {}

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
        if course_id in self.failures:
            raise self.failures[course_id]
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
            "eng002": _preview(changes=[{"action": "create_session"}], conflicting=1),
        }
    )

    result = UnifiedAcademicSyncService(siga, moodle, plans, reconciler).sync("user", now=42)

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

    result = UnifiedAcademicSyncService(_Siga(), _Moodle(courses), plans, reconciler).sync(
        "user", now=42
    )

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


def test_sync_is_not_blocked_when_stage_telemetry_delivery_fails() -> None:
    def unavailable_telemetry(_event: str, _fields: object) -> None:
        raise RuntimeError("log sink unavailable")

    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course(candidates=[])]),
        _Plans(),
        _Reconciler({}),
        telemetry=unavailable_telemetry,
    ).sync("user", now=42)

    assert result["teaching_plans"] == {
        "available": 0,
        "imported": 0,
        "applied": 0,
        "unchanged": 0,
        "review_required": 0,
    }


def test_explicitly_unpublished_plan_is_informational_and_never_reconciles_stale_data() -> None:
    class Plans(_Plans):
        def import_plan(self, user_id: str, **values: object) -> dict[str, object]:
            return {"plan": "not_published"}

    events: list[tuple[str, dict[str, object]]] = []
    reconciler = _Reconciler({})
    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course("ESA019")]),
        Plans(),
        reconciler,
        telemetry=lambda event, fields: events.append((event, dict(fields))),
    ).sync("user", now=42)
    assert reconciler.calls == []
    assert result["exceptions"][0]["reason"] == "teaching_plan_not_published"
    assert result["teaching_plans"]["imported"] == 0
    assert not any(event.endswith("_failed") for event, _ in events)
    notice = next(fields for event, fields in events if event == "academic_sync_plan_not_published")
    assert notice["course_code"] == "ESA019"
    assert notice["preserved_existing_data"] is True


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
        UnifiedAcademicSyncService(_Siga(), _Moodle(courses), _Plans(), _Reconciler({})).sync(
            "user", now=42
        )
    except ValueError as error:
        assert str(error) == "too many academic sync exceptions"
    else:
        raise AssertionError("the bounded exception contract must be enforced")


def test_sync_logs_one_unavailable_plan_and_continues_the_other_courses() -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []
    plans = _Plans(
        {
            "esa019": InvalidMoodleResponse(
                "diario_plan_structure",
                details={
                    "parser_stage": "required_sections",
                    "sample_rows": [
                        "Atividade: | DIG ESA019 CIÊNCIAS DO AMBIENTE",
                        "* Plano de Avaliação não publicado.",
                        "* Cronograma não publicado.",
                    ],
                },
            )
        }
    )
    reconciler = _Reconciler({"ele028": _preview(changes=[{"action": "create_session"}])})

    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course("ESA019"), _course("ELE028")]),
        plans,
        reconciler,
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    ).sync("user", now=42)

    assert [call[1] for call in plans.calls] == ["esa019", "ele028"]
    assert reconciler.calls == [("ele028", False), ("ele028", True)]
    assert result["teaching_plans"] == {
        "available": 2,
        "imported": 1,
        "applied": 1,
        "unchanged": 0,
        "review_required": 1,
    }
    assert result["exceptions"] == [
        {
            "course_id": "esa019",
            "course_code": "ESA019",
            "reason": "teaching_plan_unavailable",
            "candidate_count": 1,
            "changes": [],
            "conflicting": 0,
            "assessment_conflicts": 0,
        }
    ]
    course_failures = [item for item in telemetry if item[0] == "academic_sync_course_failed"]
    assert course_failures == [
        (
            "academic_sync_course_failed",
            {
                "course_id": "esa019",
                "course_code": "ESA019",
                "term": "2026-2",
                "source_id": 101,
                "stage": "teaching_plan_import",
                "reason": "diario_plan_structure",
                "exception_type": "InvalidMoodleResponse",
                "parser_stage": "required_sections",
                "sample_rows": [
                    "Atividade: | DIG ESA019 CIÊNCIAS DO AMBIENTE",
                    "* Plano de Avaliação não publicado.",
                    "* Cronograma não publicado.",
                ],
            },
        )
    ]


def test_sync_continues_after_an_isolated_reconciliation_failure() -> None:
    class Reconciler(_Reconciler):
        def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
            if course_id == "esa019":
                raise ValueError("bad saved course state")
            return super().reconcile(course_id, apply=apply)

    telemetry: list[tuple[str, dict[str, object]]] = []
    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course("ESA019"), _course("ELE028")]),
        _Plans(),
        Reconciler({"ele028": _preview()}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    ).sync("user", now=42)

    assert result["teaching_plans"] == {
        "available": 2,
        "imported": 2,
        "applied": 0,
        "unchanged": 1,
        "review_required": 1,
    }
    assert result["exceptions"][0]["course_code"] == "ESA019"
    course_failure = next(item for item in telemetry if item[0] == "academic_sync_course_failed")
    assert course_failure[1] == {
        "course_id": "esa019",
        "course_code": "ESA019",
        "term": "2026-2",
        "source_id": 101,
        "stage": "teaching_plan_reconciliation",
        "reason": "ValueError",
        "exception_type": "ValueError",
    }


def test_sync_continues_when_apply_fails_and_telemetry_is_optional() -> None:
    class Reconciler(_Reconciler):
        def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
            if course_id == "esa019" and apply:
                raise ValueError("apply failed")
            return super().reconcile(course_id, apply=apply)

    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course("ESA019"), _course("ELE028")]),
        _Plans(),
        Reconciler(
            {
                "esa019": _preview(changes=[{"action": "create_session"}]),
                "ele028": _preview(),
            }
        ),
    ).sync("user", now=42)

    assert result["teaching_plans"] == {
        "available": 2,
        "imported": 2,
        "applied": 0,
        "unchanged": 1,
        "review_required": 1,
    }
    assert result["exceptions"][0]["course_code"] == "ESA019"


def test_sync_does_not_hide_global_dependency_failures() -> None:
    class Reconciler(_Reconciler):
        def __init__(self, *, fail_on_apply: bool) -> None:
            super().__init__({"ele028": _preview(changes=[{"action": "create_session"}])})
            self.fail_on_apply = fail_on_apply

        def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
            if apply == self.fail_on_apply:
                raise MoodleUnavailable("offline")
            return super().reconcile(course_id, apply=apply)

    services = [
        UnifiedAcademicSyncService(
            _Siga(),
            _Moodle([_course()]),
            _Plans({"ele028": MoodleUnavailable("offline")}),
            _Reconciler({}),
        ),
        UnifiedAcademicSyncService(
            _Siga(), _Moodle([_course()]), _Plans(), Reconciler(fail_on_apply=False)
        ),
        UnifiedAcademicSyncService(
            _Siga(), _Moodle([_course()]), _Plans(), Reconciler(fail_on_apply=True)
        ),
    ]

    for service in services:
        with pytest.raises(MoodleUnavailable):
            service.sync("user", now=42)


def test_sync_reports_duration_and_progress_for_each_slow_stage() -> None:
    ticks = iter([0.0, 0.4, 0.4, 1.1, 1.1, 2.0, 2.0, 2.3])
    telemetry: list[tuple[str, dict[str, object]]] = []
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans(),
        _Reconciler({"ele028": _preview()}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
        monotonic=lambda: next(ticks),
    )

    service.sync("user", now=42)

    assert telemetry == [
        ("academic_sync_stage_completed", {"stage": "siga", "duration_ms": 400.0}),
        ("academic_sync_stage_completed", {"stage": "moodle", "duration_ms": 700.0}),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_import",
                "course_id": "ele028",
                "course_code": "ELE028",
                "duration_ms": 900.0,
            },
        ),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_reconciliation",
                "course_id": "ele028",
                "course_code": "ELE028",
                "duration_ms": 300.0,
            },
        ),
    ]


def test_deferred_plan_does_not_repeat_reconciliation_or_create_false_review_errors():
    from types import SimpleNamespace

    reconciler = _Reconciler({})
    plans = SimpleNamespace(import_plan=lambda *a, **k: {"plan": "deferred"})
    result = UnifiedAcademicSyncService(_Siga(), _Moodle([_course()]), plans, reconciler).sync(
        "user", now=42
    )
    assert result["teaching_plans"]["unchanged"] == 1
    assert result["exceptions"] == []
    assert reconciler.calls == []


def test_unavailable_deferred_plan_keeps_review_warning_and_other_courses_continue():
    from types import SimpleNamespace

    reconciler = _Reconciler({"mat001": _preview()})
    plans = SimpleNamespace(
        import_plan=lambda *a, **k: {
            "plan": "unavailable" if k["course_id"] == "ele028" else "created"
        }
    )
    result = UnifiedAcademicSyncService(
        _Siga(), _Moodle([_course(), _course("MAT001")]), plans, reconciler
    ).sync("user", now=42)
    assert result["teaching_plans"]["review_required"] == 1
    assert result["exceptions"][0]["course_code"] == "ELE028"
    assert reconciler.calls == [("mat001", False)]
