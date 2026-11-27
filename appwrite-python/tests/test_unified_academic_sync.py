from threading import Event

import pytest

from firestore_rest import FirestoreUnavailable
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from teaching_plan_reconciliation import InvalidTeachingPlanReconciliation
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

    def sync_siga(
        self, user_id: str, *, now: int, on_courses_imported=None, on_schedules_imported=None
    ) -> dict[str, object]:
        assert (user_id, now) == ("user", 42)
        self.calls += 1
        if on_courses_imported is not None:
            on_courses_imported()
        if on_schedules_imported is not None:
            on_schedules_imported({})
        return {"courses": {"created": 1}, "schedules": {"updated": 1}}


class _Moodle:
    def __init__(self, courses: list[dict[str, object]]) -> None:
        self.courses = courses
        self.calls = 0

    def sync(
        self,
        user_id: str,
        *,
        now: int,
        on_content_discovered=None,
    ) -> dict[str, object]:
        assert (user_id, now) == ("user", 42)
        self.calls += 1
        result = {
            "dates": {"created": 2},
            "content": {"courses": self.courses, "candidate_total": 3},
            "capabilities": {"direct_download_supported": True},
        }
        if on_content_discovered is not None:
            on_content_discovered(result["content"])
        return result


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
        include_plan_data: bool = False,
    ) -> dict[str, object]:
        self.calls.append((user_id, course_id, term, source_id, now))
        if course_id in self.failures:
            raise self.failures[course_id]
        result: dict[str, object] = {"plan": "created"}
        if include_plan_data:
            result["plan_data"] = {"schedule": [], "assessments": []}
        return result


class _Reconciler:
    def __init__(self, previews: dict[str, dict[str, object]]) -> None:
        self.previews = previews
        self.calls: list[tuple[str, bool]] = []
        self.inputs: list[tuple[str, dict[str, object] | None, list[dict[str, object]] | None]] = []

    def reconcile(
        self,
        course_id: str,
        *,
        apply: bool,
        plan_data: dict[str, object] | None = None,
        meetings_data: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self.calls.append((course_id, apply))
        self.inputs.append((course_id, plan_data, meetings_data))
        preview = self.previews[course_id]
        return {**preview, "applied": len(preview["changes"]) if apply else 0}


def _preview(
    *,
    changes: list[dict[str, object]] | None = None,
    conflicting: int = 0,
    assessment_conflicts: int = 0,
    excluded: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    preview = {
        "changes": changes or [],
        "conflicting": conflicting,
        "assessment_conflicts": assessment_conflicts,
    }
    if excluded is not None:
        preview["excluded"] = excluded
    return preview


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


def test_sync_reports_excluded_plan_rows_and_keeps_other_work_successful() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    excluded = [{"action": "excluded", "reason": "unsupported_lesson_count"}]
    reconciler = _Reconciler(
        {"ele028": _preview(changes=[{"action": "create_session"}], excluded=excluded)}
    )

    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans(),
        reconciler,
        telemetry=lambda event, fields: events.append((event, dict(fields))),
    ).sync("user", now=42)

    assert reconciler.calls == [("ele028", False), ("ele028", True)]
    assert result["teaching_plans"] == {
        "available": 1,
        "imported": 1,
        "applied": 1,
        "unchanged": 0,
        "review_required": 1,
    }
    assert result["exceptions"][0]["reason"] == ("teaching_plan_occurrences_not_representable")
    assert result["exceptions"][0]["excluded"] == excluded
    event, fields = next(
        item for item in events if item[0] == "academic_sync_plan_occurrences_excluded"
    )
    assert fields["excluded_count"] == 1
    assert fields["safe_changes_apply_status"] == "applied"
    assert fields["safe_changes_count"] == 1
    assert fields["safe_changes_still_applied"] is True


def test_apply_failure_merges_with_excluded_occurrence_for_same_course() -> None:
    class ApplyFails(_Reconciler):
        def reconcile(
            self, course_id: str, *, apply: bool, plan_data=None, meetings_data=None
        ) -> dict[str, object]:
            self.calls.append((course_id, apply))
            if apply:
                raise ValueError("firestore failed")
            return self.previews[course_id]

    telemetry: list[tuple[str, dict[str, object]]] = []
    excluded = [{"action": "excluded", "reason": "unsupported_lesson_count"}]
    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans(),
        ApplyFails({"ele028": _preview(changes=[{"action": "create_session"}], excluded=excluded)}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    ).sync("user", now=42)

    assert result["teaching_plans"]["review_required"] == 1
    assert len(result["exceptions"]) == 1
    exception = result["exceptions"][0]
    assert exception["reason"] == "teaching_plan_occurrences_not_representable"
    assert exception["excluded"] == excluded
    assert exception["apply_error"] == "ValueError"
    event = next(
        fields for name, fields in telemetry if name == "academic_sync_plan_occurrences_excluded"
    )
    assert event["safe_changes_apply_status"] == "failed"
    assert event["safe_changes_still_applied"] is False
    assert event["apply_error"] == "ValueError"


def test_excluded_only_plan_reports_that_safe_apply_was_not_needed() -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []
    excluded = [{"action": "excluded", "reason": "unsupported_lesson_count"}]
    result = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans(),
        _Reconciler({"ele028": _preview(excluded=excluded)}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    ).sync("user", now=42)

    assert result["teaching_plans"]["review_required"] == 1
    event = next(
        fields for name, fields in telemetry if name == "academic_sync_plan_occurrences_excluded"
    )
    assert event["safe_changes_apply_status"] == "not_needed"
    assert event["safe_changes_count"] == 0
    assert event["safe_changes_still_applied"] is True


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
        def reconcile(
            self, course_id: str, *, apply: bool, plan_data=None, meetings_data=None
        ) -> dict[str, object]:
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
        def reconcile(
            self, course_id: str, *, apply: bool, plan_data=None, meetings_data=None
        ) -> dict[str, object]:
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

        def reconcile(
            self, course_id: str, *, apply: bool, plan_data=None, meetings_data=None
        ) -> dict[str, object]:
            if apply == self.fail_on_apply:
                raise MoodleUnavailable("offline")
            return super().reconcile(course_id, apply=apply)

    services = [
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


def test_single_plan_http_500_is_reported_without_failing_other_courses() -> None:
    events = []
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans({"ele028": MoodleUnavailable(upstream_status=500)}),
        _Reconciler({}),
        telemetry=lambda event, fields: events.append((event, fields)),
    )
    result = service.sync("user", now=42)
    assert result["teaching_plans"]["review_required"] == 1
    assert result["exceptions"][0]["reason"] == "teaching_plan_unavailable"
    failure = next(fields for event, fields in events if event == "academic_sync_course_failed")
    assert failure["upstream_status"] == 500
    assert failure["timed_out"] is False


@pytest.mark.parametrize("status", [None, 404])
def test_single_plan_non_server_http_failure_remains_fatal(status: int | None) -> None:
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans({"ele028": MoodleUnavailable(upstream_status=status)}),
        _Reconciler({}),
    )
    with pytest.raises(MoodleUnavailable):
        service.sync("user", now=42)


def test_plan_reconciliation_failure_details_are_logged() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    error = InvalidTeachingPlanReconciliation(
        "lesson_duration_mismatch", course_id="ele028", duration_minutes=60
    )
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans({"ele028": error}),
        _Reconciler({}),
        telemetry=lambda event, fields: events.append((event, dict(fields))),
    )

    result = service.sync("user", now=42)

    assert result["teaching_plans"]["review_required"] == 1
    failure = next(fields for event, fields in events if event == "academic_sync_course_failed")
    assert failure["reason"] == "lesson_duration_mismatch"
    assert failure["course_id"] == "ele028"
    assert failure["duration_minutes"] == 60


def test_plan_firestore_unavailable_remains_fatal() -> None:
    service = UnifiedAcademicSyncService(
        _Siga(), _Moodle([_course()]), _Plans({"ele028": FirestoreUnavailable()}), _Reconciler({})
    )
    with pytest.raises(FirestoreUnavailable):
        service.sync("user", now=42)


def test_parallel_plan_workers_emit_dependency_graph() -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course(), _course("MAT001")]),
        _Plans(),
        _Reconciler({"ele028": _preview(), "mat001": _preview()}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
        plan_workers=2,
    )

    result = service.sync("user", now=42)

    assert result["teaching_plans"]["available"] == 2
    graph = [fields for event, fields in telemetry if event == "sync_span_graph"]
    assert graph and graph[0]["root"] == "academic_sync"
    assert any(
        node["name"] == "teaching_plan_import" and node["parallel_group"] == "teaching_plans"
        for node in graph[0]["nodes"]
    )


def test_teaching_plan_worker_count_is_bounded() -> None:
    with pytest.raises(ValueError, match="invalid teaching plan concurrency"):
        UnifiedAcademicSyncService(_Siga(), _Moodle([]), _Plans(), _Reconciler({}), plan_workers=0)


def test_sync_reports_duration_and_progress_for_each_slow_stage() -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []
    service = UnifiedAcademicSyncService(
        _Siga(),
        _Moodle([_course()]),
        _Plans(),
        _Reconciler({"ele028": _preview()}),
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    )

    service.sync("user", now=42)

    completed = {
        fields["stage"]: fields
        for event, fields in telemetry
        if event == "academic_sync_stage_completed"
    }
    assert {"siga", "moodle", "teaching_plan_import", "teaching_plan_reconciliation"} <= set(
        completed
    )
    assert all(
        isinstance(completed[stage]["duration_ms"], (int, float))
        and completed[stage]["duration_ms"] >= 0
        for stage in ("siga", "moodle", "teaching_plan_import", "teaching_plan_reconciliation")
    )
    dispatch_index = next(
        index
        for index, (event, _) in enumerate(telemetry)
        if event == "academic_sync_plans_dispatched"
    )
    moodle_index = next(
        index
        for index, (event, fields) in enumerate(telemetry)
        if event == "academic_sync_stage_completed" and fields.get("stage") == "moodle"
    )
    assert dispatch_index < moodle_index
    lineage = next(fields for event, fields in telemetry if event == "academic_sync_lineage")
    expected = {
        "source": "teaching_plan",
        "dataset": "assessments_and_schedule",
        "consumer": "course_dates_and_teaching_plan_view",
        "courses_considered": 1,
        "plans_imported": 1,
        "changes_applied": 0,
        "unchanged": 1,
        "review_required": 0,
        "overlap_policy": "plan_assessments_reconcile_into_course_dates",
    }
    assert {key: lineage[key] for key in expected} == expected
    diario_endpoint = (
        "GET/POST https://sistemas.ufmg.br/diario/JasperServlet "
        "(official Diário document/transition)"
    )
    assert diario_endpoint in lineage["endpoints"]
    assert any(
        destination["path"] == "courses/{course_id}/sessions/{session_id}"
        for destination in lineage["destinations"]
    )


def test_plan_import_starts_as_soon_as_content_discovery_completes() -> None:
    plan_started = Event()

    class Plans(_Plans):
        def import_plan(self, *args, **kwargs):
            plan_started.set()
            return {"plan": "deferred"}

    class Moodle(_Moodle):
        def sync(self, user_id, *, now, on_content_discovered=None):
            assert on_content_discovered is not None
            on_content_discovered({"courses": self.courses})
            assert plan_started.wait(timeout=2)
            return super().sync(user_id, now=now)

    result = UnifiedAcademicSyncService(
        _Siga(),
        Moodle([_course()]),
        Plans(),
        _Reconciler({"ele028": _preview()}),
        plan_workers=2,
    ).sync("user", now=42)

    assert plan_started.is_set()
    assert result["teaching_plans"]["unchanged"] == 1


def test_plan_reconciliation_waits_for_siga_schedule_import() -> None:
    plan_import_finished = Event()
    schedules_imported = Event()

    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            assert on_courses_imported is not None
            on_courses_imported()
            # Let Moodle discover the plan and let the worker fetch it while
            # this thread is still importing the SIGA schedule.
            assert plan_import_finished.wait(timeout=2)
            assert not schedules_imported.is_set()
            schedules_imported.set()
            return {"courses": {"created": 1}, "schedules": {"updated": 1}}

    class Plans(_Plans):
        def import_plan(self, *args, **kwargs):
            result = super().import_plan(*args, **kwargs)
            plan_import_finished.set()
            return result

    class Reconciler(_Reconciler):
        def reconcile(self, course_id, *, apply, plan_data=None, meetings_data=None):
            assert schedules_imported.is_set()
            return super().reconcile(course_id, apply=apply)

    result = UnifiedAcademicSyncService(
        Siga(),
        _Moodle([_course()]),
        Plans(),
        Reconciler({"ele028": _preview()}),
        plan_workers=2,
    ).sync("user", now=42)

    assert plan_import_finished.is_set()
    assert result["teaching_plans"]["imported"] == 1
    assert result["teaching_plans"]["unchanged"] == 1


def test_plan_reconciliation_reuses_the_imported_plan_and_siga_schedule_snapshot() -> None:
    meetings = [{"id": "monday-1900", "weekday": 1, "start_minutes": 1140}]

    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            if on_courses_imported is not None:
                on_courses_imported()
            assert on_schedules_imported is not None
            on_schedules_imported({"ele028": meetings})
            return {"courses": {}, "schedules": {}}

    reconciler = _Reconciler({"ele028": _preview()})
    UnifiedAcademicSyncService(Siga(), _Moodle([_course()]), _Plans(), reconciler).sync(
        "user", now=42
    )

    _, plan_data, meetings_data = reconciler.inputs[0]
    assert plan_data == {"schedule": [], "assessments": []}
    assert meetings_data is meetings


def test_plan_reconciliation_is_skipped_when_siga_schedule_import_fails() -> None:
    plan_import_finished = Event()
    telemetry: list[tuple[str, dict[str, object]]] = []
    reconciler = _Reconciler({"ele028": _preview()})

    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            assert on_courses_imported is not None
            on_courses_imported()
            assert plan_import_finished.wait(timeout=2)
            raise RuntimeError("SIGA schedule import failed")

    class Plans(_Plans):
        def import_plan(self, *args, **kwargs):
            result = super().import_plan(*args, **kwargs)
            plan_import_finished.set()
            return result

    with pytest.raises(RuntimeError, match="SIGA schedule import failed"):
        UnifiedAcademicSyncService(
            Siga(),
            _Moodle([_course()]),
            Plans(),
            reconciler,
            telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
            plan_workers=2,
        ).sync("user", now=42)

    assert reconciler.calls == []
    skipped = [
        fields
        for event, fields in telemetry
        if event == "academic_sync_plan_reconciliation_skipped"
    ]
    assert skipped == [
        {
            "course_id": "ele028",
            "course_code": "ELE028",
            "reason": "siga_schedule_import_failed",
        }
    ]


def test_plan_dispatch_ignores_repeated_content_notifications() -> None:
    class Moodle(_Moodle):
        def sync(self, user_id, *, now, on_content_discovered=None):
            assert on_content_discovered is not None
            content = {"courses": self.courses}
            on_content_discovered(content)
            on_content_discovered(content)
            return {"dates": {}, "content": content, "capabilities": {}}

    result = UnifiedAcademicSyncService(
        _Siga(), Moodle([_course()]), _Plans(), _Reconciler({"ele028": _preview()}), plan_workers=2
    ).sync("user", now=42)

    assert result["teaching_plans"]["available"] == 1
    assert result["teaching_plans"]["unchanged"] == 1


@pytest.mark.parametrize("courses", ["not-a-list", [None]])
def test_plan_dispatch_rejects_invalid_discovered_course_list(courses) -> None:
    class Moodle(_Moodle):
        def sync(self, user_id, *, now, on_content_discovered=None):
            assert on_content_discovered is not None
            on_content_discovered({"courses": courses})
            raise AssertionError("invalid discovery must stop the sync")

    with pytest.raises(ValueError, match="invalid discovered teaching plan courses"):
        UnifiedAcademicSyncService(
            _Siga(), Moodle([]), _Plans(), _Reconciler({}), plan_workers=2
        ).sync("user", now=42)


def test_plan_dispatch_falls_back_to_returned_content_when_callback_is_not_called():
    class Moodle(_Moodle):
        def sync(self, user_id, *, now, on_content_discovered=None):
            return {"dates": {}, "content": {"courses": self.courses}, "capabilities": {}}

    result = UnifiedAcademicSyncService(
        _Siga(), Moodle([_course()]), _Plans(), _Reconciler({"ele028": _preview()}), plan_workers=2
    ).sync("user", now=42)

    assert result["teaching_plans"]["available"] == 1
    assert result["teaching_plans"]["unchanged"] == 1


def test_sync_starts_moodle_after_course_import_without_waiting_for_full_siga_stage():
    moodle_started = Event()

    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            assert on_courses_imported is not None
            on_courses_imported()
            assert moodle_started.wait(timeout=2)
            return {"courses": {"created": 1}, "schedules": {"updated": 1}}

    class Moodle(_Moodle):
        def sync(self, user_id, *, now, on_content_discovered=None):
            moodle_started.set()
            return super().sync(user_id, now=now, on_content_discovered=on_content_discovered)

    result = UnifiedAcademicSyncService(
        Siga(), Moodle([]), _Plans(), _Reconciler({}), plan_workers=1
    ).sync("user", now=42)

    assert moodle_started.is_set()
    assert result["moodle"]["content"]["candidate_total"] == 3


def test_siga_callback_can_be_repeated_without_starting_moodle_twice():
    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            assert on_courses_imported is not None
            on_courses_imported()
            on_courses_imported()
            return {"courses": {}, "schedules": {}}

    moodle = _Moodle([])
    UnifiedAcademicSyncService(Siga(), moodle, _Plans(), _Reconciler({})).sync("user", now=42)

    assert moodle.calls == 1


def test_sync_starts_moodle_after_siga_returns_without_course_callback():
    class Siga(_Siga):
        def sync_siga(self, user_id, *, now, on_courses_imported=None, on_schedules_imported=None):
            assert on_courses_imported is not None
            return {"courses": {}, "schedules": {}}

    moodle = _Moodle([])
    result = UnifiedAcademicSyncService(Siga(), moodle, _Plans(), _Reconciler({})).sync(
        "user", now=42
    )

    assert moodle.calls == 1
    assert result["moodle"]["content"]["candidate_total"] == 3


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
