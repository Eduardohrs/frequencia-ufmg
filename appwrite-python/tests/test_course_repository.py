from typing import Any

import pytest

from course_repository import CourseRepository, DuplicateCourseCode, validate_course_id
from course_service import InvalidCourse, course_to_firestore


def _course(course_id: str = "course-1", code: str = "DCC203") -> dict[str, object]:
    return {
        "id": course_id,
        "code": code,
        "name": "POO",
        "workload": 1,
        "term": "2026-2",
        "starts_on": None,
        "ends_on": None,
        "created_at": "2026-10-04T12:00:00Z",
        "updated_at": "2026-10-04T12:00:00Z",
    }


def _document(course: dict[str, object]) -> dict[str, object]:
    return {
        "name": f"projects/p/databases/(default)/documents/users/u/courses/{course['id']}",
        "fields": course_to_firestore(course),
    }


class FakeFirestore:
    def __init__(self, courses: list[dict[str, object]] | None = None) -> None:
        self.courses = courses or []
        self.deleted: list[tuple[str, ...]] = []
        self.deleted_batches: list[list[tuple[str, ...]]] = []
        self.children = {
            "meetings": [{"name": "root/meeting-1"}],
            "sessions": [{"name": "root/session-1"}],
        }

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        if segments == ("courses",):
            return self.courses
        return self.children[segments[-1]]

    def patch_user_document(self, *segments: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {"name": f"root/{segments[-1]}", "fields": fields}

    def delete_user_document(self, *segments: str) -> None:
        self.deleted.append(segments)

    def delete_user_documents(self, paths: list[tuple[str, ...]]) -> None:
        self.deleted_batches.append(paths)


def test_repository_lists_sorted_courses_and_saves_updates() -> None:
    store = FakeFirestore([_document(_course("two", "MAT001")), _document(_course())])
    repository = CourseRepository(store)  # type: ignore[arg-type]

    assert [course["code"] for course in repository.list_courses()] == ["DCC203", "MAT001"]
    assert repository.save_course(_course())["id"] == "course-1"


def test_repository_rejects_duplicate_code_for_a_different_course() -> None:
    repository = CourseRepository(FakeFirestore([_document(_course())]))  # type: ignore[arg-type]

    with pytest.raises(DuplicateCourseCode):
        repository.save_course(_course("course-2"))


def test_repository_cascades_children_before_course_delete() -> None:
    store = FakeFirestore()
    repository = CourseRepository(store)  # type: ignore[arg-type]

    repository.delete_course("course-1")

    assert store.deleted_batches == [
        [
            ("courses", "course-1", "meetings", "meeting-1"),
            ("courses", "course-1", "sessions", "session-1"),
            ("courses", "course-1"),
        ]
    ]


@pytest.mark.parametrize("value", [None, "", " x", "x/y", "x\\y", "x" * 129])
def test_course_id_validation_rejects_unsafe_values(value: object) -> None:
    with pytest.raises(InvalidCourse):
        validate_course_id(value)


@pytest.mark.parametrize(
    "document",
    [{}, {"name": 3, "fields": {}}, {"name": "root/id"}, {"name": "root/"}],
)
def test_repository_rejects_malformed_firestore_documents(document: dict[str, object]) -> None:
    repository = CourseRepository(FakeFirestore([document]))  # type: ignore[arg-type]

    with pytest.raises(InvalidCourse):
        repository.list_courses()
