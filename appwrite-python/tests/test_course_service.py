from datetime import UTC, datetime

import pytest

from course_service import (
    InvalidCourse,
    course_from_firestore,
    course_to_firestore,
    validate_course,
)


def _course() -> dict[str, object]:
    return {
        "id": "course-1",
        "code": "DCC203",
        "name": "Programacao Orientada a Objetos",
        "workload": 1,
        "term": "2026-2",
        "starts_on": "2026-08-03T00:00:00Z",
        "ends_on": "2026-12-12T00:00:00Z",
        "created_at": "2026-10-04T12:00:00Z",
        "updated_at": "2026-10-04T12:00:00Z",
    }


def test_course_round_trips_through_firestore_fields() -> None:
    course = validate_course(_course())
    restored = course_from_firestore("course-1", course_to_firestore(course))
    assert restored == course


@pytest.mark.parametrize("modality,policy", [("online", "no_call"), ("in_person", "no_call")])
def test_course_policy_survives_firestore_without_changing_history(
    modality: str, policy: str,
) -> None:
    course = {**_course(), "modality": modality, "attendance_policy": policy}
    assert course_from_firestore("course-1", course_to_firestore(course)) == course


@pytest.mark.parametrize("change", [
    {"modality": "unknown"}, {"attendance_policy": "unknown"},
    {"modality": "online", "attendance_policy": "required"},
    {"modality": None}, {"attendance_policy": False},
])
def test_course_rejects_invalid_attendance_policy(change: dict[str, object]) -> None:
    with pytest.raises(InvalidCourse):
        validate_course({**_course(), **change})


@pytest.mark.parametrize(
    "change",
    [
        {"extra": True},
        {"id": "bad/id"},
        {"code": "dcc203"},
        {"name": " "},
        {"workload": True},
        {"workload": 0},
        {"term": "2026-3"},
        {"starts_on": None},
        {"ends_on": "2026-07-01T00:00:00Z"},
        {"updated_at": "2026-10-03T12:00:00Z"},
        {"created_at": 3},
        {"created_at": "x"},
        {"created_at": "2026-10-04T12:00:00"},
    ],
)
def test_course_rejects_invalid_or_noncanonical_input(change: dict[str, object]) -> None:
    with pytest.raises(InvalidCourse):
        validate_course({**_course(), **change})


def test_course_rejects_malformed_firestore_document() -> None:
    with pytest.raises(InvalidCourse):
        course_from_firestore("course-1", {"code": {"stringValue": "DCC203"}})

    fields = course_to_firestore(validate_course(_course()))
    fields["schemaVersion"] = {"integerValue": "2"}
    with pytest.raises(InvalidCourse):
        course_from_firestore("course-1", fields)

    fields = course_to_firestore(validate_course(_course()))
    fields["startsOn"] = {"stringValue": "bad"}
    with pytest.raises(InvalidCourse):
        course_from_firestore("course-1", fields)


def test_course_accepts_null_date_pair() -> None:
    course = validate_course({**_course(), "starts_on": None, "ends_on": None})
    assert course["starts_on"] is None
    assert course["ends_on"] is None
    created = datetime.fromisoformat(str(course["created_at"]).replace("Z", "+00:00"))
    assert created.tzinfo == UTC
