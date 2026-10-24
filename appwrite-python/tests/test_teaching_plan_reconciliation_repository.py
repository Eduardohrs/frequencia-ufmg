from datetime import UTC, datetime
from typing import Any

from course_service import course_to_firestore
from schedule_repository import _meeting_to_firestore
from teaching_plan_reconciliation_repository import TeachingPlanReconciliationRepository
from teaching_plan_repository import TeachingPlanRepository

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


class Store:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}
        self.commits: list[list[Any]] = []
        self.deletes: list[list[tuple[str, ...]]] = []

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        return self.documents[segments]

    def patch_user_document(self, *segments: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.documents[segments] = {"name": "/".join(segments), "fields": fields}
        return self.documents[segments]

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        return [
            value
            for path, value in self.documents.items()
            if path[:-1] == segments
        ]

    def commit_user_documents(self, *, updates: list[Any], deletes: list[Any]) -> None:
        self.commits.append(updates)
        self.deletes.append(deletes)
        for path, fields in updates:
            self.documents[path] = {"name": "/".join(path), "fields": fields}
        for path in deletes:
            self.documents.pop(path, None)


def _plan() -> dict[str, object]:
    return {
        "term": "2026-2",
        "course_code": "DCC203",
        "course_name": "POO",
        "class_group": "T1",
        "assessments": [],
        "undated_assessment_total": 0,
        "criteria": [],
        "schedule": [{
            "sequence": 1,
            "occurrence_key": "2026-08-10T19:00-20:40",
            "date": "2026-08-10",
            "weekday": "Seg",
            "lesson_count": 2,
            "starts_at": "19:00",
            "ends_at": "20:40",
            "kind": "Teórica",
            "subject": "Polimorfismo",
        }],
        "source": "ufmg_diario",
        "confidence": "authoritative",
    }


def _course() -> dict[str, object]:
    return {
        "id": "poo",
        "code": "DCC203",
        "name": "POO",
        "workload": 2,
        "term": "2026-2",
        "starts_on": None,
        "ends_on": None,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def test_preview_never_writes_and_apply_is_idempotent() -> None:
    store = Store()
    store.documents[("courses", "poo")] = {
        "name": "courses/poo",
        "fields": course_to_firestore(_course()),
    }
    TeachingPlanRepository(store, now=lambda: NOW).save(
        "poo", source_id="1", plan=_plan()
    )
    store.documents[("courses", "poo", "meetings", "monday-1900")] = {
        "name": "courses/poo/meetings/monday-1900",
        "fields": _meeting_to_firestore({
            "id": "monday-1900",
            "weekday": 1,
            "start_minutes": 1140,
            "end_minutes": 1240,
            "lesson_count": 2,
            "call_count": 1,
            "created_at": "2026-08-01T12:00:00Z",
            "updated_at": "2026-08-01T12:00:00Z",
        }),
    }
    repository = TeachingPlanReconciliationRepository(store, now=lambda: NOW)

    preview = repository.reconcile("poo", apply=False)
    assert preview == {
        "course_id": "poo",
        "mode": "preview",
        "matched": 0,
        "missing": 1,
        "conflicting": 0,
        "assessments_linked": 0,
        "assessment_conflicts": 0,
        "outside_schedule": 0,
        "applied": 0,
        "changes": [{
            "action": "create_session",
            "occurrence_key": "2026-08-10T19:00-20:40",
            "date": "2026-08-10",
            "starts_at": "19:00",
            "ends_at": "20:40",
            "subject": "Polimorfismo",
        }],
        "excluded": [],
        "conflicts": [],
        "workload_validation": {
            "status": "aligned",
            "expected_lesson_units": 2,
            "actual_lesson_units": 2,
            "difference_lesson_units": 0,
            "expected_typical_meetings": 1,
            "active_encounters": 1,
            "excluded_encounters": 0,
            "scheduled_lesson_units": 2,
            "no_call_lesson_units": 0,
            "makeup_lesson_units": 0,
        },
    }
    assert store.commits == []

    applied = repository.reconcile("poo", apply=True)
    assert applied["applied"] == 1
    assert len(store.commits) == 1
    repeated = repository.reconcile("poo", apply=True)
    assert repeated["matched"] == 1
    assert repeated["applied"] == 0
    assert len(store.commits) == 1


def test_apply_removes_an_untouched_import_outside_the_saved_grade() -> None:
    store = Store()
    store.documents[("courses", "poo")] = {
        "name": "courses/poo",
        "fields": course_to_firestore(_course()),
    }
    TeachingPlanRepository(store, now=lambda: NOW).save(
        "poo", source_id="1", plan=_plan()
    )
    store.documents[("courses", "poo", "sessions", "2026-08-10--diario-1900-2040")] = {
        "name": "courses/poo/sessions/2026-08-10--diario-1900-2040",
        "fields": {
            "schemaVersion": {"integerValue": "1"},
            "startsAt": {"timestampValue": "2026-08-10T22:00:00Z"},
            "endsAt": {"timestampValue": "2026-08-10T23:40:00Z"},
            "lessonCount": {"integerValue": "2"},
            "callCount": {"integerValue": "1"},
            "firstPing": {"nullValue": None},
            "secondPing": {"nullValue": None},
            "attendanceStatus": {"nullValue": None},
            "absences": {"nullValue": None},
            "calendarStatus": {"stringValue": "scheduled"},
            "assessmentTitle": {"nullValue": None},
            "createdAt": {"timestampValue": "2026-08-01T12:00:00Z"},
            "updatedAt": {"timestampValue": "2026-08-01T12:00:00Z"},
        },
    }
    repository = TeachingPlanReconciliationRepository(store, now=lambda: NOW)
    result = repository.reconcile("poo", apply=True)

    assert result["applied"] == 1
    assert result["changes"][0]["action"] == "remove_session"
    assert store.deletes[-1] == [
        ("courses", "poo", "sessions", "2026-08-10--diario-1900-2040")
    ]
    repeated = repository.reconcile("poo", apply=True)
    assert repeated["applied"] == 0
    assert repeated["outside_schedule"] == 1
    assert len(store.commits) == 1


def test_legacy_placeholder_workload_is_not_reported_as_one_hour() -> None:
    store = Store()
    store.documents[("courses", "poo")] = {
        "name": "courses/poo",
        "fields": course_to_firestore({**_course(), "workload": 1}),
    }
    TeachingPlanRepository(store, now=lambda: NOW).save(
        "poo", source_id="1", plan=_plan()
    )

    result = TeachingPlanReconciliationRepository(store, now=lambda: NOW).reconcile(
        "poo", apply=False
    )

    assert result["workload_validation"] is None
