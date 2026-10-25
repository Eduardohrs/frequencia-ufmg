"""Read-only preview and additive persistence for Diário occurrences."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

from course_repository import CourseRepository, validate_course_id
from firestore_rest import FirestoreRestClient
from schedule_repository import _decode_meeting, _decode_session, _session_to_firestore
from teaching_plan_reconciliation import reconcile_teaching_plan_schedule
from teaching_plan_repository import TeachingPlanRepository


class TeachingPlanReconciliationRepository:
    def __init__(
        self,
        firestore: FirestoreRestClient,
        *,
        now: Callable[[], datetime] | None = None,
        courses: CourseRepository | None = None,
        telemetry: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))
        self._plans = TeachingPlanRepository(firestore, now=self._now)
        self._courses = courses or CourseRepository(firestore)
        self._telemetry = telemetry

    def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
        identifier = validate_course_id(course_id)
        course = self._courses.get_course(identifier)
        persisted = self._plans.load(identifier)
        plan = cast(dict[str, object], persisted["plan"])
        sessions = [
            _decode_session(document)
            for document in self._firestore.list_user_documents("courses", identifier, "sessions")
        ]
        meetings = [
            _decode_meeting(document)
            for document in self._firestore.list_user_documents("courses", identifier, "meetings")
        ]
        online = course.get("modality") == "online"
        preview = reconcile_teaching_plan_schedule(
            [] if online else plan.get("schedule"),
            [] if online else sessions,
            assessments=[] if online else plan.get("assessments"),
            meetings=[] if online else meetings,
            workload=None if course["workload"] == 1 or online
            else int(course["workload"]),
            now=self._now(),
        )
        applied = 0
        writes = (*preview.creates, *preview.updates)
        if apply and (writes or preview.delete_ids):
            self._firestore.commit_user_documents(
                updates=[
                    (
                        ("courses", identifier, "sessions", str(item["id"])),
                        _session_to_firestore(item),
                    )
                    for item in writes
                ],
                deletes=[
                    ("courses", identifier, "sessions", session_id)
                    for session_id in preview.delete_ids
                ],
            )
            applied = len(writes) + len(preview.delete_ids)
        if self._telemetry is not None:
            self._telemetry("teaching_plan_course_policy_preserved", {
                "course_id": identifier, "course_code": course["code"],
                "modality": course.get("modality", "in_person"),
                "attendance_policy": course.get("attendance_policy", "required"),
                "existing_sessions": len(sessions), "applied": applied,
                "mode": "apply" if apply else "preview",
                "attendance_records_preserved": True,
            })
        return {
            "course_id": identifier,
            "mode": "applied" if apply else "preview",
            **preview.counts,
            "applied": applied,
            "changes": list(preview.changes),
            "excluded": list(preview.excluded),
            "conflicts": list(preview.conflicts),
            "workload_validation": preview.workload_validation,
        }
