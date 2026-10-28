"""Authenticated course operations over the user's existing Firestore tree."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from course_service import (
    InvalidCourse,
    course_from_firestore,
    course_to_firestore,
    validate_course,
)
from firestore_rest import FirestoreRestClient
from schedule_service import InvalidSchedule, require_mutable_term


class DuplicateCourseCode(Exception):
    """Another course already owns the same canonical code."""


class CourseRepository:
    def __init__(
        self,
        firestore: FirestoreRestClient,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))
        self._course_snapshot: list[dict[str, Any]] | None = None

    def list_courses(self) -> list[dict[str, Any]]:
        if self._course_snapshot is None:
            courses = [
                self._decode(document)
                for document in self._firestore.list_user_documents("courses")
            ]
            self._course_snapshot = sorted(
                courses, key=lambda course: (course["code"], course["id"])
            )
        return [dict(course) for course in self._course_snapshot]

    def get_course(self, course_id: str) -> dict[str, Any]:
        identifier = validate_course_id(course_id)
        if self._course_snapshot is not None:
            for course in self._course_snapshot:
                if course["id"] == identifier:
                    return dict(course)
        return self._decode(self._firestore.get_user_document("courses", identifier))

    def save_course(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        course = validate_course(payload)
        existing_courses = self.list_courses()
        if any(
            existing["id"] != course["id"] and existing["code"] == course["code"]
            for existing in existing_courses
        ):
            raise DuplicateCourseCode("duplicate course code")
        if not any(existing["id"] == course["id"] for existing in existing_courses):
            try:
                require_mutable_term(str(course["term"]), self._now().date())
            except InvalidSchedule:
                raise InvalidCourse("invalid course") from None
        document = self._firestore.patch_user_document(
            "courses", str(course["id"]), fields=course_to_firestore(course)
        )
        saved = course_from_firestore(str(course["id"]), _fields(document))
        self._course_snapshot = None
        return saved

    def delete_course(self, course_id: str) -> None:
        validate_course_id(course_id)
        paths: list[tuple[str, ...]] = []
        for collection in (
            "meetings",
            "sessions",
            "academicDates",
            "materialCatalog",
            "teachingPlans",
            "activitySnapshots",
        ):
            documents = self._firestore.list_user_documents("courses", course_id, collection)
            for document in documents:
                child_id = _document_id(document)
                paths.append(("courses", course_id, collection, child_id))
        paths.append(("courses", course_id))
        self._firestore.delete_user_documents(paths)
        self._course_snapshot = None

    @staticmethod
    def _decode(document: Mapping[str, Any]) -> dict[str, Any]:
        return course_from_firestore(_document_id(document), _fields(document))


def validate_course_id(course_id: object) -> str:
    if (
        not isinstance(course_id, str)
        or not course_id
        or len(course_id) > 128
        or course_id.strip() != course_id
        or "/" in course_id
        or "\\" in course_id
    ):
        raise InvalidCourse("invalid course")
    return course_id


def _document_id(document: Mapping[str, Any]) -> str:
    name = document.get("name")
    if not isinstance(name, str):
        raise InvalidCourse("invalid course")
    return validate_course_id(name.rsplit("/", 1)[-1])


def _fields(document: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = document.get("fields")
    if not isinstance(fields, Mapping):
        raise InvalidCourse("invalid course")
    return fields
