"""Atomic schedule persistence over the user's existing Firestore tree."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from course_repository import validate_course_id
from course_service import course_from_firestore, course_to_firestore
from firestore_rest import FirestoreRestClient
from schedule_service import (
    InvalidSchedule,
    SchedulePlan,
    build_schedule_plan,
    validate_saved_meeting,
    validate_saved_session,
)


class DestructiveScheduleChange(Exception):
    """A schedule replacement would delete evidence-bearing sessions."""

    def __init__(self, count: int) -> None:
        super().__init__("destructive schedule change")
        self.count = count


class ScheduleRepository:
    def __init__(
        self,
        firestore: FirestoreRestClient,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def get_schedule(self, course_id: str) -> dict[str, Any]:
        """Return persisted state and a read-only reconciliation preview."""

        course, meetings, sessions, others = self._load(course_id)
        plan = build_schedule_plan(
            course=course,
            requested_starts_on=course["starts_on"],
            requested_ends_on=course["ends_on"],
            requested_meetings=[_meeting_input(item) for item in meetings],
            existing_meetings=meetings,
            existing_sessions=sessions,
            other_schedules=others,
            now=self._now(),
        )
        return _response(plan)

    def save_schedule(
        self,
        course_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate and atomically persist a complete schedule replacement."""

        if set(payload) != {"starts_on", "ends_on", "meetings", "confirm_destructive"}:
            raise InvalidSchedule("invalid schedule")
        confirm = payload["confirm_destructive"]
        if type(confirm) is not bool:
            raise InvalidSchedule("invalid schedule")
        course, meetings, sessions, others = self._load(course_id)
        plan = build_schedule_plan(
            course=course,
            requested_starts_on=payload["starts_on"],
            requested_ends_on=payload["ends_on"],
            requested_meetings=payload["meetings"],
            existing_meetings=meetings,
            existing_sessions=sessions,
            other_schedules=others,
            now=self._now(),
        )
        if plan.destructive_delete_count and not confirm:
            raise DestructiveScheduleChange(plan.destructive_delete_count)
        updates, deletes = _writes(course_id, course, plan)
        if updates or deletes:
            self._firestore.commit_user_documents(updates=updates, deletes=deletes)
        return _response(plan)

    def _load(
        self, course_id: str
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[tuple[dict[str, Any], list[dict[str, Any]]]],
    ]:
        identifier = validate_course_id(course_id)
        course = _decode_course(self._firestore.get_user_document("courses", identifier))
        meetings = [
            _decode_meeting(document)
            for document in self._firestore.list_user_documents("courses", identifier, "meetings")
        ]
        sessions = [
            _decode_session(document)
            for document in self._firestore.list_user_documents("courses", identifier, "sessions")
        ]
        others: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for document in self._firestore.list_user_documents("courses"):
            other = _decode_course(document)
            if other["id"] == identifier:
                continue
            other_meetings = [
                _decode_meeting(item)
                for item in self._firestore.list_user_documents(
                    "courses", str(other["id"]), "meetings"
                )
            ]
            others.append((other, other_meetings))
        return course, meetings, sessions, others


def _writes(
    course_id: str,
    original_course: Mapping[str, Any],
    plan: SchedulePlan,
) -> tuple[
    list[tuple[tuple[str, ...], Mapping[str, Any]]],
    list[tuple[str, ...]],
]:
    updates: list[tuple[tuple[str, ...], Mapping[str, Any]]] = []
    if plan.course != original_course:
        updates.append((("courses", course_id), course_to_firestore(plan.course)))
    updates.extend(
        (("courses", course_id, "meetings", str(item["id"])), _meeting_to_firestore(item))
        for item in plan.meeting_upserts
    )
    updates.extend(
        (("courses", course_id, "sessions", str(item["id"])), _session_to_firestore(item))
        for item in plan.session_upserts
    )
    deletes: list[tuple[str, ...]] = [
        *(("courses", course_id, "meetings", item) for item in plan.meeting_delete_ids),
        *(("courses", course_id, "sessions", item) for item in plan.session_delete_ids),
    ]
    return updates, deletes


def _response(plan: SchedulePlan) -> dict[str, Any]:
    return {
        "course": plan.course,
        "meetings": list(plan.meetings),
        "changes": {
            "meeting_upserts": len(plan.meeting_upserts),
            "meeting_deletes": len(plan.meeting_delete_ids),
            "session_upserts": len(plan.session_upserts),
            "session_deletes": len(plan.session_delete_ids),
            "destructive_deletes": plan.destructive_delete_count,
        },
    }


def _meeting_input(meeting: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: meeting[key]
        for key in ("id", "weekday", "start_minutes", "lesson_count", "call_count")
    }


def _decode_course(document: Mapping[str, Any]) -> dict[str, Any]:
    return course_from_firestore(_document_id(document), _fields(document))


def _decode_meeting(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = _fields(document)
    try:
        payload = {
            "id": _document_id(document),
            "weekday": _integer(fields, "weekday"),
            "start_minutes": _integer(fields, "startMinutes"),
            "end_minutes": _integer(fields, "endMinutes"),
            "lesson_count": _integer(fields, "lessonCount"),
            "call_count": _integer(fields, "callCount"),
            "created_at": _timestamp(fields, "createdAt"),
            "updated_at": _timestamp(fields, "updatedAt"),
        }
        if fields["schemaVersion"] != {"integerValue": "1"}:
            raise KeyError
    except (KeyError, TypeError, ValueError):
        raise InvalidSchedule("invalid schedule") from None
    return validate_saved_meeting(payload)


def _decode_session(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = _fields(document)
    try:
        if fields["schemaVersion"] != {"integerValue": "1"}:
            raise KeyError
        payload = {
            "id": _document_id(document),
            "starts_at": _timestamp(fields, "startsAt"),
            "ends_at": _timestamp(fields, "endsAt"),
            "lesson_count": _integer(fields, "lessonCount"),
            "call_count": _integer(fields, "callCount"),
            "first_ping": _nullable_string(fields, "firstPing"),
            "second_ping": _nullable_string(fields, "secondPing"),
            "attendance_status": _nullable_string(fields, "attendanceStatus"),
            "absences": _nullable_integer(fields, "absences"),
            "calendar_status": _optional_string(fields, "calendarStatus", "scheduled"),
            "assessment_title": _nullable_string(fields, "assessmentTitle", missing=True),
            "created_at": _timestamp(fields, "createdAt"),
            "updated_at": _timestamp(fields, "updatedAt"),
        }
    except (KeyError, TypeError, ValueError):
        raise InvalidSchedule("invalid schedule") from None
    return validate_saved_session(payload)


def _meeting_to_firestore(meeting: Mapping[str, Any]) -> dict[str, Any]:
    valid = validate_saved_meeting(meeting)
    return {
        "schemaVersion": {"integerValue": "1"},
        "weekday": _firestore_integer(valid["weekday"]),
        "startMinutes": _firestore_integer(valid["start_minutes"]),
        "endMinutes": _firestore_integer(valid["end_minutes"]),
        "lessonCount": _firestore_integer(valid["lesson_count"]),
        "callCount": _firestore_integer(valid["call_count"]),
        "createdAt": {"timestampValue": valid["created_at"]},
        "updatedAt": {"timestampValue": valid["updated_at"]},
    }


def _session_to_firestore(session: Mapping[str, Any]) -> dict[str, Any]:
    valid = validate_saved_session(session)
    return {
        "schemaVersion": {"integerValue": "1"},
        "startsAt": {"timestampValue": valid["starts_at"]},
        "endsAt": {"timestampValue": valid["ends_at"]},
        "lessonCount": _firestore_integer(valid["lesson_count"]),
        "callCount": _firestore_integer(valid["call_count"]),
        "firstPing": _firestore_nullable(valid["first_ping"], "stringValue"),
        "secondPing": _firestore_nullable(valid["second_ping"], "stringValue"),
        "attendanceStatus": _firestore_nullable(valid["attendance_status"], "stringValue"),
        "absences": _firestore_nullable(valid["absences"], "integerValue"),
        "calendarStatus": {"stringValue": valid["calendar_status"]},
        "assessmentTitle": _firestore_nullable(valid["assessment_title"], "stringValue"),
        "createdAt": {"timestampValue": valid["created_at"]},
        "updatedAt": {"timestampValue": valid["updated_at"]},
    }


def _document_id(document: Mapping[str, Any]) -> str:
    name = document.get("name")
    if not isinstance(name, str):
        raise InvalidSchedule("invalid schedule")
    return validate_course_id(name.rsplit("/", 1)[-1])


def _fields(document: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = document.get("fields")
    if not isinstance(fields, Mapping):
        raise InvalidSchedule("invalid schedule")
    return fields


def _integer(fields: Mapping[str, Any], name: str) -> int:
    return int(fields[name]["integerValue"])


def _timestamp(fields: Mapping[str, Any], name: str) -> str:
    value = fields[name]["timestampValue"]
    if not isinstance(value, str):
        raise TypeError
    return value


def _nullable_string(fields: Mapping[str, Any], name: str, *, missing: bool = False) -> str | None:
    if missing and name not in fields or fields.get(name) == {"nullValue": None}:
        return None
    value = fields[name]["stringValue"]
    if not isinstance(value, str):
        raise TypeError
    return value


def _optional_string(fields: Mapping[str, Any], name: str, default: str) -> str:
    if name not in fields:
        return default
    value = fields[name]["stringValue"]
    if not isinstance(value, str):
        raise TypeError
    return value


def _nullable_integer(fields: Mapping[str, Any], name: str) -> int | None:
    if fields.get(name) == {"nullValue": None}:
        return None
    return _integer(fields, name)


def _firestore_integer(value: object) -> dict[str, str]:
    return {"integerValue": str(value)}


def _firestore_nullable(value: object, field_type: str) -> dict[str, Any]:
    return {"nullValue": None} if value is None else {field_type: str(value)}
