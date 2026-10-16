import copy
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from moodle_material_catalog_repository import (
    MAX_CATALOG_BYTES,
    InvalidMoodleMaterialCatalog,
    MoodleMaterialCatalogRepository,
    _decode,
    _encode,
    _instant,
)

NOW = datetime(2026, 10, 16, 3, tzinfo=UTC)


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


def _candidate(**changes: object) -> dict[str, object]:
    candidate = {
        "source_id": "101",
        "moodle_course_id": "3701",
        "kind": "file",
        "title": "Plano de ensino",
        "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=101",
        "relevance": "teaching_plan",
        "origin": "canonical",
        **changes,
    }
    if "source_id" in changes and "url" not in changes:
        candidate["url"] = (
            f"https://virtual.ufmg.br/20262/mod/resource/view.php?id={candidate['source_id']}"
        )
    return candidate


def _course(**changes: object) -> dict[str, object]:
    return {
        "course_id": "course-a",
        "course_code": "DCC203",
        "term": "2026-2",
        "moodle_course_id": "3701",
        "status": "found",
        "candidates": [_candidate()],
        **changes,
    }


def test_reconcile_is_idempotent_and_counts_item_changes() -> None:
    firestore = _Firestore()
    repository = MoodleMaterialCatalogRepository(firestore, now=lambda: NOW)

    first = repository.reconcile([_course()])
    second = repository.reconcile([_course()])
    changed = repository.reconcile(
        [
            _course(
                candidates=[
                    _candidate(title="Plano atualizado"),
                    _candidate(
                        source_id="102",
                        moodle_course_id="4999",
                        title="Lista da metaturma",
                        origin="metaturma",
                    ),
                ]
            )
        ]
    )
    removed = repository.reconcile(
        [
            _course(
                candidates=[
                    _candidate(
                        source_id="102",
                        moodle_course_id="4999",
                        title="Lista da metaturma",
                        origin="metaturma",
                    )
                ]
            )
        ]
    )

    assert first == {"created": 1, "updated": 0, "unchanged": 0, "removed": 0, "writes": 1}
    assert second == {"created": 0, "updated": 0, "unchanged": 1, "removed": 0, "writes": 0}
    assert changed == {"created": 1, "updated": 1, "unchanged": 0, "removed": 0, "writes": 1}
    assert removed == {"created": 0, "updated": 0, "unchanged": 1, "removed": 1, "writes": 1}
    assert len(firestore.patches) == 3


def test_list_returns_persisted_catalog_with_explicit_origin_and_course_identity() -> None:
    firestore = _Firestore()
    repository = MoodleMaterialCatalogRepository(firestore, now=lambda: NOW)
    metaturma = _candidate(
        source_id="102",
        moodle_course_id="4999",
        title="Lista da metaturma",
        origin="metaturma",
    )
    repository.reconcile([_course(candidates=[_candidate(), metaturma])])

    catalog = repository.list_catalog([{"id": "course-a", "code": "DCC203", "term": "2026-2"}])

    assert catalog == [
        {
            "course_id": "course-a",
            "course_code": "DCC203",
            "term": "2026-2",
            "moodle_course_id": "3701",
            "status": "found",
            "candidates": [_candidate(), metaturma],
        }
    ]


def test_reconcile_replaces_removed_materials_and_preserves_empty_states() -> None:
    firestore = _Firestore()
    repository = MoodleMaterialCatalogRepository(firestore, now=lambda: NOW)
    repository.reconcile([_course()])

    result = repository.reconcile([_course(status="empty", candidates=[])])

    assert result == {"created": 0, "updated": 0, "unchanged": 0, "removed": 1, "writes": 1}
    assert (
        repository.list_catalog([{"id": "course-a", "code": "DCC203", "term": "2026-2"}])[0][
            "status"
        ]
        == "empty"
    )


@pytest.mark.parametrize(
    "course",
    [
        _course(candidates=[_candidate(), _candidate()]),
        _course(candidates=[_candidate(origin="unknown")]),
        _course(candidates=[_candidate(moodle_course_id="bad")]),
        _course(candidates=[_candidate(url="https://attacker.example/file")]),
        _course(status="empty"),
        _course(status="unmatched", moodle_course_id="3701", candidates=[]),
        {**_course(), "unexpected": True},
    ],
)
def test_reconcile_rejects_invalid_catalog_without_writes(course: dict[str, object]) -> None:
    firestore = _Firestore()

    with pytest.raises(InvalidMoodleMaterialCatalog):
        MoodleMaterialCatalogRepository(firestore, now=lambda: NOW).reconcile([course])

    assert firestore.patches == []


def test_list_rejects_corrupt_or_mismatched_persisted_catalogs() -> None:
    firestore = _Firestore()
    repository = MoodleMaterialCatalogRepository(firestore, now=lambda: NOW)
    repository.reconcile([_course()])
    path = ("courses", "course-a", "materialCatalog", "current")
    firestore.documents[path]["contentHash"] = {"stringValue": "0" * 64}

    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.list_catalog([{"id": "course-a", "code": "DCC203", "term": "2026-2"}])


def test_empty_and_default_clock_are_supported() -> None:
    repository = MoodleMaterialCatalogRepository(_Firestore())

    assert repository.reconcile([]) == {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
        "writes": 0,
    }
    assert repository.list_catalog([]) == []


def test_reconcile_rejects_global_bounds_and_duplicate_courses() -> None:
    repository = MoodleMaterialCatalogRepository(_Firestore(), now=lambda: NOW)
    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.reconcile([_course()] * 51)
    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.reconcile([_course(), _course()])

    first = [
        _candidate(source_id=str(index), title=f"Material {index}")
        for index in range(1, 301)
    ]
    second = [
        _candidate(source_id=str(index), title=f"Material {index}")
        for index in range(301, 601)
    ]
    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.reconcile(
            [
                _course(candidates=first),
                _course(course_id="course-b", course_code="MAT001", candidates=second),
            ]
        )


@pytest.mark.parametrize(
    "course",
    [
        {},
        {"id": "bad/id", "code": "DCC203", "term": "2026-2"},
        {"id": "course-a", "code": 1, "term": "2026-2"},
        {"id": "course-a", "code": "lower", "term": "2026-2"},
        {"id": "course-a", "code": "DCC203", "term": 1},
        {"id": "course-a", "code": "DCC203", "term": "invalid"},
    ],
)
def test_list_rejects_invalid_course_metadata(course: dict[str, object]) -> None:
    with pytest.raises(InvalidMoodleMaterialCatalog):
        MoodleMaterialCatalogRepository(_Firestore()).list_catalog([course])


def test_list_skips_missing_catalog_and_rejects_mismatch_or_multiple_documents() -> None:
    firestore = _Firestore()
    repository = MoodleMaterialCatalogRepository(firestore, now=lambda: NOW)
    course = {"id": "course-a", "code": "DCC203", "term": "2026-2"}
    assert repository.list_catalog([course]) == []

    repository.reconcile([_course()])
    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.list_catalog([{**course, "term": "2026-1"}])

    fields = copy.deepcopy(
        firestore.documents[("courses", "course-a", "materialCatalog", "current")]
    )
    firestore.documents[("courses", "course-a", "materialCatalog", "other")] = fields
    with pytest.raises(InvalidMoodleMaterialCatalog):
        repository.list_catalog([course])


@pytest.mark.parametrize(
    "changes",
    [
        {"course_id": "bad/id"},
        {"course_code": 1},
        {"course_code": "lower"},
        {"term": 1},
        {"term": "invalid"},
        {"status": "unknown"},
        {"candidates": "not-a-list"},
        {"candidates": [_candidate(source_id=str(index)) for index in range(1, 502)]},
        {"status": "unmatched", "moodle_course_id": None, "candidates": [_candidate()]},
        {"status": "found", "moodle_course_id": None},
    ],
)
def test_reconcile_rejects_each_invalid_course_field(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidMoodleMaterialCatalog):
        MoodleMaterialCatalogRepository(_Firestore()).reconcile([_course(**changes)])


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        {**_candidate(), "extra": True},
        _candidate(kind="unknown"),
        _candidate(title=1),
        _candidate(title=""),
        _candidate(title=" padded "),
        _candidate(title="x" * 1_025),
        _candidate(relevance="unknown"),
        _candidate(origin="unknown"),
        _candidate(kind="text"),
        _candidate(url=None),
        _candidate(url=1),
        _candidate(url="x" * 4_097),
        _candidate(url="http://virtual.ufmg.br/20262/mod/resource/view.php?id=101"),
        _candidate(url="https://other.example/20262/mod/resource/view.php?id=101"),
        _candidate(url="https://user@virtual.ufmg.br/20262/mod/resource/view.php?id=101"),
        _candidate(url="https://user:pass@virtual.ufmg.br/20262/mod/resource/view.php?id=101"),
        _candidate(url="https://virtual.ufmg.br/20262/mod/resource/view.php?id=101#x"),
        _candidate(url="https://virtual.ufmg.br/20262/mod/page/view.php?id=101"),
        _candidate(url="https://virtual.ufmg.br/20262/mod/resource/view.php?id=102"),
        _candidate(source_id=1),
        _candidate(source_id="0"),
        _candidate(source_id="2147483648"),
    ],
)
def test_reconcile_rejects_each_invalid_candidate_field(candidate: object) -> None:
    with pytest.raises(InvalidMoodleMaterialCatalog):
        MoodleMaterialCatalogRepository(_Firestore()).reconcile(
            [_course(candidates=[candidate])]
        )


def test_encode_rejects_an_oversized_material_payload() -> None:
    with pytest.raises(InvalidMoodleMaterialCatalog):
        _encode(
            {
                "term": "2026-2",
                "status": "found",
                "moodle_course_id": "3701",
                "candidates": [{"origin": "canonical", "title": "x" * MAX_CATALOG_BYTES}],
                "created_at": "2026-10-16T03:00:00Z",
                "updated_at": "2026-10-16T03:00:00Z",
            }
        )


def _stored_document() -> dict[str, Any]:
    firestore = _Firestore()
    MoodleMaterialCatalogRepository(firestore, now=lambda: NOW).reconcile([_course()])
    return {
        "name": "courses/course-a/materialCatalog/current",
        "fields": copy.deepcopy(
            firestore.documents[("courses", "course-a", "materialCatalog", "current")]
        ),
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "fields_not_map",
        "extra_field",
        "schema",
        "materials_not_string",
        "materials_too_large",
        "hash_not_string",
        "hash_mismatch",
        "json_not_list",
        "candidate_count",
        "metaturma_count",
        "created_format",
        "updated_format",
        "updated_before_created",
        "missing_name",
    ],
)
def test_decode_rejects_every_corrupt_persisted_shape(mutation: str) -> None:
    document = _stored_document()
    fields = document["fields"]
    if mutation == "fields_not_map":
        document["fields"] = None
    elif mutation == "extra_field":
        fields["extra"] = {"stringValue": "x"}
    elif mutation == "schema":
        fields["schemaVersion"] = {"integerValue": "2"}
    elif mutation == "materials_not_string":
        fields["materialsJson"] = {"stringValue": 1}
    elif mutation == "materials_too_large":
        fields["materialsJson"] = {"stringValue": "x" * (MAX_CATALOG_BYTES + 1)}
    elif mutation == "hash_not_string":
        fields["contentHash"] = {"stringValue": 1}
    elif mutation == "hash_mismatch":
        fields["contentHash"] = {"stringValue": "0" * 64}
    elif mutation == "json_not_list":
        raw = "{}"
        fields["materialsJson"] = {"stringValue": raw}
        fields["contentHash"] = {"stringValue": hashlib.sha256(raw.encode()).hexdigest()}
    elif mutation == "candidate_count":
        fields["candidateCount"] = {"integerValue": "2"}
    elif mutation == "metaturma_count":
        fields["metaturmaCandidateCount"] = {"integerValue": "1"}
    elif mutation == "created_format":
        fields["createdAt"] = {"timestampValue": "not-an-instant"}
    elif mutation == "updated_format":
        fields["updatedAt"] = {"timestampValue": 1}
    elif mutation == "updated_before_created":
        fields["updatedAt"] = {"timestampValue": "2026-10-15T03:00:00Z"}
    else:
        document.pop("name")

    with pytest.raises(InvalidMoodleMaterialCatalog):
        if mutation == "missing_name":
            firestore = _Firestore()
            firestore.documents[("courses", "course-a", "materialCatalog", "current")] = fields
            broken = firestore.list_user_documents("courses", "course-a", "materialCatalog")[0]
            broken.pop("name")
            # Exercise the document-name guard directly because the fake rebuilds names.
            from moodle_material_catalog_repository import _document_id

            _document_id(broken)
        else:
            _decode(document)


def test_instant_rejects_long_and_timezone_less_values() -> None:
    with pytest.raises(InvalidMoodleMaterialCatalog):
        _instant("x" * 41)
    with pytest.raises(InvalidMoodleMaterialCatalog):
        _instant("2026-10-16T03:00:00")
