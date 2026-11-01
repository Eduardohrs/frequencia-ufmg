"""Persist bounded session mutations below the verified Firebase user."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from checkpoint_service import checkpoint_decision, validate_checkpoint_payload
from course_repository import CourseRepository, validate_course_id
from firestore_rest import FirestoreRestClient, FirestoreUnavailable
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
        self.checkpoint_stage = "validation"
        self.checkpoint_stage_started = perf_counter()

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
        self._save(
            course,
            session,
            updated,
            ("attendanceStatus", "absences", "updatedAt"),
        )
        return {
            "status": updated["attendance_status"],
            "absences": updated["absences"],
            "updated_at": updated["updated_at"],
        }

    def apply_checkpoints(
        self,
        course_id: str,
        session_id: str,
        payload: object,
    ) -> dict[str, Any]:
        course, identifier = self._identifiers(course_id, session_id)
        evidence = validate_checkpoint_payload(payload)
        started = perf_counter()
        self._checkpoint_stage("course_read")
        saved_course = CourseRepository(self._firestore).get_course(course)
        course_ms = int((perf_counter() - started) * 1000)
        self._checkpoint_stage("session_read")
        document = self._firestore.get_user_document("courses", course, "sessions", identifier)
        current = _decode_session(document)
        read_ms = int((perf_counter() - started) * 1000) - course_ms
        self._checkpoint_stage("classification")
        if saved_course.get("attendance_policy", "required") != "required":
            outcome, reason, updated = "preserved", "course_without_roll_call", None
        else:
            outcome, reason, updated = checkpoint_decision(current, evidence, now=self._now())
        if updated is not None:
            revision = document.get("updateTime")
            if not isinstance(revision, str) or not revision:
                raise FirestoreUnavailable("checkpoint revision unavailable")
            names = ("firstPing", "secondPing", "attendanceStatus", "absences", "updatedAt")
            encoded = _session_to_firestore(updated)
            self._checkpoint_stage("conditional_write")
            self._firestore.patch_user_document(
                "courses",
                course,
                "sessions",
                identifier,
                fields={key: encoded[key] for key in names},
                update_mask=names,
                expected_update_time=revision,
            )
        result = updated or current
        return {
            "outcome": outcome,
            "reason": reason,
            "status": result["attendance_status"],
            "absences": result["absences"],
            "first_ping": result["first_ping"],
            "second_ping": result["second_ping"],
            "first_operation_id": evidence["first"]["operation_id"] if evidence["first"] else None,
            "second_operation_id": evidence["second"]["operation_id"]
            if evidence["second"]
            else None,
            "course_read_ms": course_ms,
            "session_read_ms": read_ms,
            "write_ms": int((perf_counter() - started) * 1000) - course_ms - read_ms,
        }

    def _checkpoint_stage(self, name: str) -> None:
        self.checkpoint_stage = name
        self.checkpoint_stage_started = perf_counter()

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
        self._save(course, session, updated, ("calendarStatus", "updatedAt"))
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
        field_names: tuple[str, ...],
    ) -> None:
        complete_fields = _session_to_firestore(session)
        fields = {field: complete_fields[field] for field in field_names}
        self._firestore.patch_user_document(
            "courses",
            course_id,
            "sessions",
            session_id,
            fields=fields,
            update_mask=field_names,
        )

    @staticmethod
    def _identifiers(course_id: str, session_id: str) -> tuple[str, str]:
        return validate_course_id(course_id), validate_course_id(session_id)
