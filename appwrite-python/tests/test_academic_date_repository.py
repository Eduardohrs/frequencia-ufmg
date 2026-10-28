from datetime import UTC, datetime
from typing import Any

import pytest

from academic_date_repository import (
    AcademicDateRepository,
    InvalidAcademicDate,
    _instant,
)


class _Firestore:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}
        self.patches: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.commits: list[
            tuple[list[tuple[tuple[str, ...], dict[str, Any]]], list[tuple[str, ...]]]
        ] = []

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        prefix = tuple(segments)
        return [
            {"name": "/".join(path), "fields": fields}
            for path, fields in self.documents.items()
            if path[:-1] == prefix
        ]

    def patch_user_document(self, *segments: str, fields: dict[str, Any]) -> dict[str, Any]:
        path = tuple(segments)
        self.documents[path] = fields
        self.patches.append((path, fields))
        return {"name": "/".join(path), "fields": fields}

    def commit_user_documents(
        self,
        *,
        updates: list[tuple[tuple[str, ...], dict[str, Any]]],
        deletes: list[tuple[str, ...]],
    ) -> None:
        self.commits.append((updates, deletes))
        for path, fields in updates:
            self.documents[path] = fields
        for path in deletes:
            self.documents.pop(path, None)


NOW = datetime(2026, 10, 13, 20, tzinfo=UTC)


def _event(**changes: object) -> dict[str, object]:
    return {
        "source_id": "910",
        "title": "Trabalho prático 1",
        "due_at": "2026-10-22T23:00:00Z",
        "kind": "assignment",
        **changes,
    }


def test_import_is_idempotent_and_preserves_creation_time() -> None:
    firestore = _Firestore()
    repository = AcademicDateRepository(firestore, now=lambda: NOW)

    first = repository.import_moodle_dates("course-a", [_event()])
    second = repository.import_moodle_dates("course-a", [_event()])
    changed = repository.import_moodle_dates(
        "course-a", [_event(title="Trabalho prático 1 — adiado")]
    )

    assert first == {"total": 1, "created": 1, "updated": 0, "unchanged": 0}
    assert second == {"total": 1, "created": 0, "updated": 0, "unchanged": 1}
    assert changed == {"total": 1, "created": 0, "updated": 1, "unchanged": 0}
    assert len(firestore.patches) == 2
    saved = firestore.documents[("courses", "course-a", "academicDates", "moodle-910")]
    assert saved["createdAt"] == {"timestampValue": "2026-10-13T20:00:00Z"}
    assert saved["updatedAt"] == {"timestampValue": "2026-10-13T20:00:00Z"}
    assert saved["title"] == {"stringValue": "Trabalho prático 1 — adiado"}


def test_list_returns_canonical_dates_sorted_by_due_time() -> None:
    firestore = _Firestore()
    repository = AcademicDateRepository(firestore, now=lambda: NOW)
    repository.import_moodle_dates(
        "course-a",
        [
            _event(source_id="2", title="Depois", due_at="2026-11-01T00:00:00Z"),
            _event(source_id="1", title="Antes"),
        ],
    )

    dates = repository.list_dates("course-a")

    assert [item["source_id"] for item in dates] == ["1", "2"]
    assert dates[0]["source"] == "moodle"
    assert dates[0]["id"] == "moodle-1"


@pytest.mark.parametrize(
    "event",
    [
        _event(source_id="bad/id"),
        _event(title=""),
        _event(due_at="2026-10-22"),
        _event(kind="unknown"),
        {**_event(), "extra": True},
    ],
)
def test_import_rejects_invalid_dates_without_writes(event: dict[str, object]) -> None:
    firestore = _Firestore()
    with pytest.raises(InvalidAcademicDate):
        AcademicDateRepository(firestore, now=lambda: NOW).import_moodle_dates("course-a", [event])
    assert firestore.patches == []


def test_import_rejects_duplicates_and_oversized_batches() -> None:
    repository = AcademicDateRepository(_Firestore(), now=lambda: NOW)
    with pytest.raises(InvalidAcademicDate):
        repository.import_moodle_dates("course-a", [_event(), _event()])
    with pytest.raises(InvalidAcademicDate):
        repository.import_moodle_dates(
            "course-a", [_event(source_id=str(index + 1)) for index in range(501)]
        )


def test_default_clock_and_empty_import_are_supported() -> None:
    result = AcademicDateRepository(_Firestore()).import_moodle_dates("course-a", [])
    assert result == {"total": 0, "created": 0, "updated": 0, "unchanged": 0}


def test_diario_assessments_reconcile_without_touching_other_sources() -> None:
    firestore = _Firestore()
    repository = AcademicDateRepository(firestore, now=lambda: NOW)
    repository.import_moodle_dates("course-a", [_event()])

    first = repository.import_diario_assessments(
        "course-a",
        plan_source_id="701",
        assessments=[
            {
                "code": "AV1",
                "title": "Primeira prova",
                "scheduled_at": "2026-09-09T20:50:00-03:00",
            },
            {
                "code": "AV2",
                "title": "Segunda prova",
                "scheduled_at": "2026-10-19T20:50:00-03:00",
            },
        ],
    )
    second = repository.import_diario_assessments(
        "course-a",
        plan_source_id="701",
        assessments=[
            {
                "code": "AV2",
                "title": "Segunda prova adiada",
                "scheduled_at": "2026-10-26T20:50:00-03:00",
            }
        ],
    )

    assert first == {"total": 2, "created": 2, "updated": 0, "unchanged": 0, "removed": 0}
    assert second == {"total": 1, "created": 0, "updated": 1, "unchanged": 0, "removed": 1}
    dates = repository.list_dates("course-a")
    assert {(item["source"], item["source_id"]) for item in dates} == {
        ("moodle", "910"),
        ("diario", "701-AV2"),
    }


def test_diario_assessment_import_is_idempotent_without_an_extra_commit() -> None:
    firestore = _Firestore()
    repository = AcademicDateRepository(firestore, now=lambda: NOW)
    assessments = [
        {
            "code": "AV1",
            "title": "Primeira prova",
            "scheduled_at": "2026-09-09T20:50:00-03:00",
        }
    ]
    repository.import_diario_assessments("course-a", plan_source_id="701", assessments=assessments)
    result = repository.import_diario_assessments(
        "course-a", plan_source_id="701", assessments=assessments
    )
    assert result == {
        "total": 1,
        "created": 0,
        "updated": 0,
        "unchanged": 1,
        "removed": 0,
    }
    assert len(firestore.commits) == 1


def test_diario_assessment_import_rejects_invalid_batches() -> None:
    repository = AcademicDateRepository(_Firestore(), now=lambda: NOW)
    with pytest.raises(InvalidAcademicDate):
        repository.import_diario_assessments("course-a", plan_source_id="bad/id", assessments=[])
    duplicate = {
        "code": "AV1",
        "title": "Primeira prova",
        "scheduled_at": "2026-09-09T20:50:00-03:00",
    }
    with pytest.raises(InvalidAcademicDate):
        repository.import_diario_assessments(
            "course-a", plan_source_id="701", assessments=[duplicate, duplicate]
        )


@pytest.mark.parametrize(
    "fields",
    [
        None,
        {},
        {"schemaVersion": {"integerValue": "2"}},
    ],
)
def test_list_rejects_malformed_persisted_documents(fields: object) -> None:
    firestore = _Firestore()
    firestore.documents[("courses", "course-a", "academicDates", "broken")] = fields  # type: ignore[assignment]
    with pytest.raises(InvalidAcademicDate):
        AcademicDateRepository(firestore).list_dates("course-a")


def test_list_rejects_wrong_source_id_and_backwards_audit_time() -> None:
    firestore = _Firestore()
    repository = AcademicDateRepository(firestore, now=lambda: NOW)
    repository.import_moodle_dates("course-a", [_event()])
    path = ("courses", "course-a", "academicDates", "moodle-910")
    firestore.documents[path]["source"] = {"stringValue": "manual"}
    with pytest.raises(InvalidAcademicDate):
        repository.list_dates("course-a")

    firestore.documents[path]["source"] = {"stringValue": "moodle"}
    firestore.documents[path]["schemaVersion"] = {"integerValue": "2"}
    with pytest.raises(InvalidAcademicDate):
        repository.list_dates("course-a")

    firestore.documents[path]["schemaVersion"] = {"integerValue": "1"}
    firestore.documents[path]["createdAt"] = {"timestampValue": "2026-10-14T20:00:00Z"}
    with pytest.raises(InvalidAcademicDate):
        repository.list_dates("course-a")


@pytest.mark.parametrize("value", [None, "x" * 41, "not-a-date", "2026-10-13T20:00:00"])
def test_instant_rejects_invalid_and_timezone_free_values(value: object) -> None:
    with pytest.raises(InvalidAcademicDate):
        _instant(value)


def test_complete_moodle_snapshot_removes_only_stale_moodle_dates() -> None:
    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    repository.import_moodle_dates("course-a", [_event()])
    repository.import_diario_assessments(
        "course-a",
        plan_source_id="20",
        assessments=[{"code": "AV1", "title": "Prova", "scheduled_at": "2026-11-01T12:00:00Z"}],
    )
    repository.import_moodle_dates("course-a", [], complete=False)
    assert len(repository.list_dates("course-a")) == 2
    result = repository.import_moodle_dates("course-a", [], complete=True)
    assert result["removed"] == 1
    assert [row["source"] for row in repository.list_dates("course-a")] == ["diario"]


def test_manual_date_crud_and_imported_override_survive_complete_import() -> None:
    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    payload = {key: value for key, value in _event().items() if key != "source_id"}
    repository.save_date("course-a", "manual-personal", payload)
    assert repository.list_dates("course-a")[0]["source"] == "manual"
    repository.save_date("course-a", "manual-personal", {**payload, "title": "Edited"})
    assert repository.list_dates("course-a")[0]["title"] == "Edited"
    repository.delete_date("course-a", "manual-personal")
    assert repository.list_dates("course-a") == []
    repository.import_moodle_dates("course-a", [_event()])
    repository.save_date("course-a", "moodle-910", {**payload, "title": "My correction"})
    repository.import_moodle_dates("course-a", [_event(title="Upstream edit")], complete=True)
    assert repository.list_dates("course-a")[0]["title"] == "My correction"
    repository.import_moodle_dates("course-a", [], complete=True)
    assert repository.list_dates("course-a")[0]["manual_override"] is True


def test_manual_date_mutations_reject_unsafe_inputs_before_writing() -> None:
    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    payload = {key: value for key, value in _event().items() if key != "source_id"}
    for identifier in ["../other", "invalid-x", "moodle-new"]:
        with pytest.raises(InvalidAcademicDate):
            repository.save_date("course-a", identifier, payload)
    for invalid in [{}, {**payload, "extra": True}, {**payload, "due_at": "2026-10-01"}]:
        with pytest.raises(InvalidAcademicDate):
            repository.save_date("course-a", "manual-new", invalid)
    repository.delete_date("course-a", "manual-missing")
    assert store.patches == []
    assert store.commits == []


def test_complete_date_replacement_rejects_oversized_batch_without_partial_writes() -> None:
    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    repository.import_moodle_dates("course-a", [_event(source_id=str(i)) for i in range(500)])
    before = dict(store.documents)
    with pytest.raises(InvalidAcademicDate, match="atomic batch"):
        repository.import_moodle_dates(
            "course-a", [_event(source_id=str(i)) for i in range(500, 1000)], complete=True
        )
    assert store.documents == before
    assert store.commits == []


def test_manual_override_validation_and_diario_corrections_are_preserved() -> None:
    from academic_date_repository import _date_identifier

    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    with pytest.raises(InvalidAcademicDate):
        _date_identifier(None)
    with pytest.raises(InvalidAcademicDate):
        repository.delete_date("course-a", "moodle-1")
    assessment = {"code": "AV1", "title": "Prova", "scheduled_at": "2026-11-01T12:00:00Z"}
    repository.import_diario_assessments("course-a", plan_source_id="20", assessments=[assessment])
    repository.save_date(
        "course-a",
        "diario-20-AV1",
        {"title": "Personal correction", "kind": "assessment", "due_at": "2026-11-01T13:00:00Z"},
    )
    repository.import_diario_assessments("course-a", plan_source_id="20", assessments=[assessment])
    repository.import_diario_assessments("course-a", plan_source_id="20", assessments=[])
    assert repository.list_dates("course-a")[0]["title"] == "Personal correction"
    fields = next(iter(store.documents.values()))
    fields["manualOverride"] = {"booleanValue": False}
    assert "manual_override" not in repository.list_dates("course-a")[0]
    fields["manualOverride"] = {"booleanValue": "not a boolean"}
    with pytest.raises(InvalidAcademicDate):
        repository.list_dates("course-a")


def test_snapshot_removes_only_queried_months_using_the_moodle_local_timezone() -> None:
    store = _Firestore()
    repository = AcademicDateRepository(store, now=lambda: NOW)
    repository.import_moodle_dates(
        "course-a",
        [
            _event(source_id="october"),
            _event(source_id="future", due_at="2027-01-15T12:00:00Z"),
            _event(source_id="december-local", due_at="2027-01-01T02:00:00Z"),
        ],
    )
    result = repository.import_moodle_dates(
        "course-a", [], complete=True, covered_months=[(2026, m) for m in range(7, 13)]
    )
    assert result["removed"] == 2
    assert [item["source_id"] for item in repository.list_dates("course-a")] == ["future"]
