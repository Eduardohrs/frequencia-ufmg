"""Read-only preview and additive persistence for Diário occurrences."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

from course_repository import validate_course_id
from firestore_rest import FirestoreRestClient
from schedule_repository import _decode_session, _session_to_firestore
from teaching_plan_reconciliation import reconcile_teaching_plan_schedule
from teaching_plan_repository import TeachingPlanRepository


class TeachingPlanReconciliationRepository:
    def __init__(
        self, firestore: FirestoreRestClient, *, now: Callable[[], datetime] | None = None
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))
        self._plans = TeachingPlanRepository(firestore, now=self._now)

    def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
        identifier = validate_course_id(course_id)
        persisted = self._plans.load(identifier)
        plan = cast(dict[str, object], persisted["plan"])
        sessions = [
            _decode_session(document)
            for document in self._firestore.list_user_documents(
                "courses", identifier, "sessions"
            )
        ]
        preview = reconcile_teaching_plan_schedule(
            plan.get("schedule"), sessions, now=self._now()
        )
        applied = 0
        if apply and preview.creates:
            self._firestore.commit_user_documents(
                updates=[
                    (
                        ("courses", identifier, "sessions", str(item["id"])),
                        _session_to_firestore(item),
                    )
                    for item in preview.creates
                ],
                deletes=[],
            )
            applied = len(preview.creates)
        return {
            "course_id": identifier,
            "mode": "applied" if apply else "preview",
            **preview.counts,
            "applied": applied,
            "conflicts": list(preview.conflicts),
        }
