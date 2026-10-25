"""Bounded Firestore access for official-calendar reconciliation."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from course_repository import validate_course_id
from firestore_rest import FirestoreRestClient
from schedule_repository import _decode_session, _session_to_firestore
from session_service import InvalidSessionMutation, replace_calendar_status


class OfficialCalendarSessionRepository:
    def __init__(
        self,
        firestore: FirestoreRestClient,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def list_sessions(self, course_id: str) -> list[dict[str, Any]]:
        identifier = validate_course_id(course_id)
        return [
            _decode_session(document)
            for document in self._firestore.list_user_documents("courses", identifier, "sessions")
        ]

    def apply_holidays(self, changes: list[tuple[str, str]]) -> None:
        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
        now = self._now()
        for course_id, session_id in changes:
            course = validate_course_id(course_id)
            session = validate_course_id(session_id)
            current = _decode_session(
                self._firestore.get_user_document("courses", course, "sessions", session)
            )
            if current["calendar_status"] != "scheduled":
                raise InvalidSessionMutation("official calendar candidate changed")
            updated = replace_calendar_status(current, {"calendar_status": "holiday"}, now=now)
            updates.append(
                (("courses", course, "sessions", session), _session_to_firestore(updated))
            )
        self._firestore.commit_user_documents(updates=updates, deletes=[])
