"""Persist bounded session mutations below the verified Firebase user."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from course_repository import validate_course_id
from firestore_rest import FirestoreRestClient
from schedule_repository import _decode_session, _session_to_firestore
from session_service import replace_attendance, replace_calendar_status


class SessionMutationRepository:
    def __init__(
        self,
        firestore: FirestoreRestClient,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def save_attendance(
        self,
        course_id: str,
        session_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        course, session = self._identifiers(course_id, session_id)
        updated = replace_attendance(
            self._load(course, session),
            payload,
            now=self._now(),
        )
        self._save(course, session, updated)
        return {
            "status": updated["attendance_status"],
            "absences": updated["absences"],
            "updated_at": updated["updated_at"],
        }

    def save_calendar_status(
        self,
        course_id: str,
        session_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        course, session = self._identifiers(course_id, session_id)
        updated = replace_calendar_status(
            self._load(course, session),
            payload,
            now=self._now(),
        )
        self._save(course, session, updated)
        return {
            "calendar_status": updated["calendar_status"],
            "updated_at": updated["updated_at"],
        }

    def _load(self, course_id: str, session_id: str) -> dict[str, Any]:
        return _decode_session(
            self._firestore.get_user_document(
                "courses",
                course_id,
                "sessions",
                session_id,
            )
        )

    def _save(
        self,
        course_id: str,
        session_id: str,
        session: Mapping[str, Any],
    ) -> None:
        self._firestore.commit_user_documents(
            updates=[
                (
                    ("courses", course_id, "sessions", session_id),
                    _session_to_firestore(session),
                )
            ],
            deletes=[],
        )

    @staticmethod
    def _identifiers(course_id: str, session_id: str) -> tuple[str, str]:
        return validate_course_id(course_id), validate_course_id(session_id)
