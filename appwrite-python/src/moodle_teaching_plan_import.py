"""Import one official Diário teaching plan into its matching local course."""

from typing import Any, Protocol, cast

from course_repository import validate_course_id
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def fetch_diario_plan(
        self, token: str, *, term: str, source_id: int
    ) -> dict[str, object]: ...


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _Plans(Protocol):
    def save(
        self, course_id: str, *, source_id: str, plan: dict[str, object]
    ) -> str: ...


class _Dates(Protocol):
    def import_diario_assessments(
        self,
        course_id: str,
        *,
        plan_source_id: str,
        assessments: list[dict[str, object]],
    ) -> dict[str, int]: ...


class MoodleTeachingPlanImportService:
    def __init__(
        self,
        sessions: _Sessions,
        client: _Client,
        courses: _Courses,
        plans: _Plans,
        dates: _Dates,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._courses = courses
        self._plans = plans
        self._dates = dates

    def import_plan(
        self,
        user_id: str,
        *,
        course_id: str,
        term: str,
        source_id: int,
        now: int,
    ) -> dict[str, object]:
        identifier = validate_course_id(course_id)
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        courses = [course for course in self._courses.list_courses() if course["id"] == identifier]
        if len(courses) != 1 or courses[0].get("term") != term:
            raise ValueError("teaching plan does not match course")
        try:
            plan = self._client.fetch_diario_plan(
                session.token, term=term, source_id=source_id
            )
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        if plan.get("course_code") != courses[0].get("code") or plan.get("term") != term:
            raise ValueError("teaching plan does not match course")
        assessments = cast(list[dict[str, object]], plan["assessments"])
        dates = self._dates.import_diario_assessments(
            identifier,
            plan_source_id=str(source_id),
            assessments=assessments,
        )
        plan_outcome = self._plans.save(
            identifier, source_id=str(source_id), plan=plan
        )
        return {
            "course_id": identifier,
            "term": term,
            "source_id": str(source_id),
            "plan": plan_outcome,
            "assessment_total": len(assessments),
            "undated_assessment_total": cast(int, plan["undated_assessment_total"]),
            "dates_created": dates["created"],
            "dates_updated": dates["updated"],
            "dates_unchanged": dates["unchanged"],
            "dates_removed": dates["removed"],
            "criteria_total": len(cast(list[object], plan["criteria"])),
            "schedule_total": len(cast(list[object], plan["schedule"])),
            "confidence": "authoritative",
        }
