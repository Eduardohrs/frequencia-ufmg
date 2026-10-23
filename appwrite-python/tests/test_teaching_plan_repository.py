from datetime import UTC, datetime
from typing import Any

import pytest

from teaching_plan_repository import InvalidTeachingPlan, TeachingPlanRepository, _timestamp


class _Firestore:
    def __init__(self) -> None:
        self.document: dict[str, Any] | None = None
        self.writes = 0

    def get_user_document(self, *_segments: str) -> dict[str, Any]:
        if self.document is None:
            raise LookupError
        return {"name": "current", "fields": self.document}

    def patch_user_document(
        self, *_segments: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        self.document = fields
        self.writes += 1
        return {"name": "current", "fields": fields}


def _plan() -> dict[str, object]:
    return {
        "term": "2026-2",
        "course_code": "ELE631",
        "course_name": "CIRCUITOS ELÉTRICOS II",
        "class_group": "T1",
        "assessments": [],
        "undated_assessment_total": 0,
        "criteria": [{"description": "Soma", "value": "100.00"}],
        "schedule": [],
        "source": "ufmg_diario",
        "confidence": "authoritative",
    }


def test_save_is_idempotent_and_replaces_changed_structured_plan() -> None:
    firestore = _Firestore()
    repository = TeachingPlanRepository(
        firestore, now=lambda: datetime(2026, 10, 23, 18, tzinfo=UTC)
    )

    assert repository.save("course-a", source_id="701", plan=_plan()) == "created"
    assert repository.save("course-a", source_id="701", plan=_plan()) == "unchanged"
    changed = _plan()
    changed["criteria"] = [{"description": "Nova regra", "value": "100.00"}]
    assert repository.save("course-a", source_id="701", plan=changed) == "updated"
    assert firestore.writes == 2

    stored = repository.load("course-a")
    assert stored["source_id"] == "701"
    assert stored["plan"] == changed
    assert stored["collected_at"] == "2026-10-23T18:00:00Z"


@pytest.mark.parametrize("source_id", ["", "abc", "2147483648"])
def test_save_rejects_invalid_source_id(source_id: str) -> None:
    with pytest.raises(InvalidTeachingPlan):
        TeachingPlanRepository(_Firestore()).save(
            "course-a", source_id=source_id, plan=_plan()
        )


def test_rejects_invalid_plan_contracts_and_corrupted_documents() -> None:
    firestore = _Firestore()
    repository = TeachingPlanRepository(firestore)
    missing = _plan()
    missing.pop("schedule")
    with pytest.raises(InvalidTeachingPlan):
        repository.save("course-a", source_id="701", plan=missing)
    wrong_source = {**_plan(), "source": "moodle"}
    with pytest.raises(InvalidTeachingPlan):
        repository.save("course-a", source_id="701", plan=wrong_source)
    invalid_json = {**_plan(), "schedule": {1}}
    with pytest.raises(InvalidTeachingPlan):
        repository.save("course-a", source_id="701", plan=invalid_json)
    oversized = {**_plan(), "course_name": "x" * 750_001}
    with pytest.raises(InvalidTeachingPlan):
        repository.save("course-a", source_id="701", plan=oversized)

    firestore.document = {}
    with pytest.raises(InvalidTeachingPlan):
        repository.load("course-a")


def test_rejects_tampered_hash_and_naive_clock() -> None:
    firestore = _Firestore()
    repository = TeachingPlanRepository(
        firestore, now=lambda: datetime(2026, 10, 23, 18)
    )
    with pytest.raises(InvalidTeachingPlan):
        repository.save("course-a", source_id="701", plan=_plan())

    valid = TeachingPlanRepository(
        firestore, now=lambda: datetime(2026, 10, 23, 18, tzinfo=UTC)
    )
    valid.save("course-a", source_id="701", plan=_plan())
    assert firestore.document is not None
    firestore.document["contentHash"] = {"stringValue": "0" * 64}
    with pytest.raises(InvalidTeachingPlan):
        valid.load("course-a")

    with pytest.raises(InvalidTeachingPlan):
        _timestamp(datetime(2026, 10, 23))
