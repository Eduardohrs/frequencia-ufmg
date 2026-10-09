"""Bounded aggregate reads for the calendar and attendance dashboards."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from course_repository import CourseRepository
from firestore_rest import FirestoreRestClient
from schedule_repository import _decode_session

MAX_OVERVIEW_COURSES = 50
MAX_OVERVIEW_SESSIONS = 500
MAX_PARALLEL_READS = 8


class OverviewTooLarge(Exception):
    """The user's aggregate exceeds the response contract."""


class AcademicOverviewRepository:
    def __init__(self, firestore: FirestoreRestClient) -> None:
        self._firestore = firestore

    def load(self) -> list[dict[str, Any]]:
        courses = CourseRepository(self._firestore).list_courses()
        if len(courses) > MAX_OVERVIEW_COURSES:
            raise OverviewTooLarge("too many courses")
        if not courses:
            return []
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_READS, len(courses))) as executor:
            sessions_by_course = list(
                executor.map(self._sessions, (str(course["id"]) for course in courses))
            )
        if sum(map(len, sessions_by_course)) > MAX_OVERVIEW_SESSIONS:
            raise OverviewTooLarge("too many sessions")
        return [
            {"course": course, "sessions": sessions}
            for course, sessions in zip(courses, sessions_by_course, strict=True)
        ]

    def _sessions(self, course_id: str) -> list[dict[str, Any]]:
        sessions = [
            _decode_session(document)
            for document in self._firestore.list_user_documents("courses", course_id, "sessions")
        ]
        return sorted(sessions, key=lambda session: (session["starts_at"], session["id"]))
