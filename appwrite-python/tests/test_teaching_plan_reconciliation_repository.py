from datetime import UTC, datetime
from typing import Any

from teaching_plan_reconciliation_repository import TeachingPlanReconciliationRepository
from teaching_plan_repository import TeachingPlanRepository

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


class Store:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}
        self.commits: list[list[Any]] = []

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
        assert deletes == []
        self.commits.append(updates)
        for path, fields in updates:
            self.documents[path] = {"name": "/".join(path), "fields": fields}


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


def test_preview_never_writes_and_apply_is_idempotent() -> None:
    store = Store()
    TeachingPlanRepository(store, now=lambda: NOW).save(
        "poo", source_id="1", plan=_plan()
    )
    repository = TeachingPlanReconciliationRepository(store, now=lambda: NOW)

    preview = repository.reconcile("poo", apply=False)
    assert preview == {
        "course_id": "poo",
        "mode": "preview",
        "matched": 0,
        "missing": 1,
        "conflicting": 0,
        "applied": 0,
        "conflicts": [],
    }
    assert store.commits == []

    applied = repository.reconcile("poo", apply=True)
    assert applied["applied"] == 1
    assert len(store.commits) == 1
    repeated = repository.reconcile("poo", apply=True)
    assert repeated["matched"] == 1
    assert repeated["applied"] == 0
    assert len(store.commits) == 1
