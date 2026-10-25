"""Import one official Diário teaching plan into its matching local course."""

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast

from course_repository import validate_course_id
from sync_timing import Telemetry, timed_stage
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def fetch_diario_plan(self, token: str, *, term: str, source_id: int) -> dict[str, object]: ...


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _Plans(Protocol):
    def save(self, course_id: str, *, source_id: str, plan: dict[str, object]) -> str: ...


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
        *,
        telemetry: Telemetry | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._sessions = sessions
        self._client = client
        self._courses = courses
        self._plans = plans
        self._dates = dates
        self._telemetry = telemetry
        self._monotonic = monotonic

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
        context = {"course_id": identifier, "source_id": str(source_id)}
        session = self._timed(
            "teaching_plan_session_load",
            lambda: self._sessions.load(user_id, now=now),
            context,
        )
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        courses = self._timed(
            "teaching_plan_course_lookup",
            lambda: [
                course for course in self._courses.list_courses() if course["id"] == identifier
            ],
            context,
        )
        if len(courses) != 1 or courses[0].get("term") != term:
            raise ValueError("teaching plan does not match course")
        try:
            plan = self._timed(
                "teaching_plan_fetch",
                lambda: self._client.fetch_diario_plan(
                    session.token, term=term, source_id=source_id
                ),
                context,
            )
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        if plan.get("course_code") != courses[0].get("code") or plan.get("term") != term:
            raise ValueError("teaching plan does not match course")
        assessments = cast(list[dict[str, object]], plan["assessments"])
        if not assessments and not plan["criteria"] and not plan["schedule"]:
            # The parser only accepts an empty plan when the official report
            # explicitly says both sections have not been published. Keep any
            # previously imported dates and plan intact.
            return {
                "course_id": identifier,
                "term": term,
                "source_id": str(source_id),
                "plan": "not_published",
                "assessment_total": 0,
                "undated_assessment_total": 0,
                "dates_created": 0,
                "dates_updated": 0,
                "dates_unchanged": 0,
                "dates_removed": 0,
                "criteria_total": 0,
                "schedule_total": 0,
                "confidence": "authoritative",
            }
        dates = self._timed(
            "teaching_plan_assessment_import",
            lambda: self._dates.import_diario_assessments(
                identifier,
                plan_source_id=str(source_id),
                assessments=assessments,
            ),
            context,
        )
        plan_outcome = self._timed(
            "teaching_plan_save",
            lambda: self._plans.save(identifier, source_id=str(source_id), plan=plan),
            context,
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

    def _timed[T](
        self,
        stage: str,
        action: Callable[[], T],
        fields: Mapping[str, object],
    ) -> T:
        options: dict[str, object] = {
            "telemetry": self._telemetry,
            "fields": fields,
        }
        if self._monotonic is not None:
            options["clock"] = self._monotonic
        return timed_stage(stage, action, **options)  # type: ignore[arg-type]
