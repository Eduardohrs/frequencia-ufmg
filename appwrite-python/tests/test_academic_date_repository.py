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
