from dataclasses import dataclass
from typing import Any

import pytest

from moodle_teaching_plan_import import MoodleTeachingPlanImportService
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


@dataclass
class _Sessions:
    session: UFMGSession | None
    deleted: list[str]

    def load(self, _user_id: str, *, now: int) -> UFMGSession | None:
        assert now == 123
        return self.session

    def delete(self, user_id: str) -> None:
        self.deleted.append(user_id)


class _Client:
    def fetch_diario_plan(self, token: str, *, term: str, source_id: int) -> dict[str, object]:
        assert (token, term, source_id) == ("private", "2026-2", 701)
        return {
            "term": "2026-2",
            "course_code": "ELE631",
            "course_name": "CIRCUITOS ELÉTRICOS II",
            "class_group": "T1",
            "assessments": [
                {
                    "code": "AV1",
                    "title": "Primeira prova",
                    "scheduled_at": "2026-09-09T20:50:00-03:00",
                }
            ],
            "undated_assessment_total": 0,
            "criteria": [],
            "schedule": [],
            "source": "ufmg_diario",
            "confidence": "authoritative",
        }


class _Courses:
    def list_courses(self) -> list[dict[str, Any]]:
        return [{"id": "course-a", "code": "ELE631", "term": "2026-2"}]


class _Plans:
    def save(self, course_id: str, *, source_id: str, plan: Any) -> str:
        assert (course_id, source_id, plan["course_code"]) == ("course-a", "701", "ELE631")
        return "created"


class _Dates:
    def import_diario_assessments(
        self, course_id: str, *, plan_source_id: str, assessments: list[dict[str, object]]
    ) -> dict[str, int]:
        assert (course_id, plan_source_id, len(assessments)) == ("course-a", "701", 1)
        return {"total": 1, "created": 1, "updated": 0, "unchanged": 0, "removed": 0}


def test_import_matches_course_and_persists_plan_and_assessments() -> None:
    result = MoodleTeachingPlanImportService(
        _Sessions(UFMGSession("private", 1, 999), []),
        _Client(),
        _Courses(),
        _Plans(),
        _Dates(),
    ).import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)

    assert result == {
        "course_id": "course-a",
        "term": "2026-2",
        "source_id": "701",
        "plan": "created",
        "assessment_total": 1,
        "undated_assessment_total": 0,
        "dates_created": 1,
        "dates_updated": 0,
        "dates_unchanged": 0,
        "dates_removed": 0,
        "criteria_total": 0,
        "schedule_total": 0,
        "confidence": "authoritative",
    }


def test_import_reports_where_each_teaching_plan_millisecond_was_spent() -> None:
    events: list[tuple[str, dict[str, object]]] = []
    ticks = iter([0.0, 0.1, 0.1, 0.3, 0.3, 1.1, 1.1, 1.5, 1.5, 1.7])
    service = MoodleTeachingPlanImportService(
        _Sessions(UFMGSession("private", 1, 999), []),
        _Client(),
        _Courses(),
        _Plans(),
        _Dates(),
        telemetry=lambda event, fields: events.append((event, dict(fields))),
        monotonic=lambda: next(ticks),
    )

    service.import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)

    assert events == [
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_session_load",
                "duration_ms": 100,
                "course_id": "course-a",
                "source_id": "701",
            },
        ),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_course_lookup",
                "duration_ms": 200,
                "course_id": "course-a",
                "source_id": "701",
            },
        ),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_fetch",
                "duration_ms": 800,
                "course_id": "course-a",
                "source_id": "701",
            },
        ),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_assessment_import",
                "duration_ms": 400,
                "course_id": "course-a",
                "source_id": "701",
            },
        ),
        (
            "academic_sync_stage_completed",
            {
                "stage": "teaching_plan_save",
                "duration_ms": 200,
                "course_id": "course-a",
                "source_id": "701",
            },
        ),
    ]


def test_import_rejects_cross_course_plan_without_writes() -> None:
    class WrongCourse(_Client):
        def fetch_diario_plan(self, token: str, *, term: str, source_id: int) -> dict[str, object]:
            result = super().fetch_diario_plan(token, term=term, source_id=source_id)
            result["course_code"] = "MAT002"
            return result

    with pytest.raises(ValueError, match="teaching plan does not match course"):
        MoodleTeachingPlanImportService(
            _Sessions(UFMGSession("private", 1, 999), []),
            WrongCourse(),
            _Courses(),
            _Plans(),
            _Dates(),
        ).import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)


def test_import_requires_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleTeachingPlanImportService(
            _Sessions(None, []), _Client(), _Courses(), _Plans(), _Dates()
        ).import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)


def test_import_rejects_missing_or_cross_term_course() -> None:
    class WrongTerm(_Courses):
        def list_courses(self) -> list[dict[str, Any]]:
            return [{"id": "course-a", "code": "ELE631", "term": "2026-1"}]

    with pytest.raises(ValueError, match="teaching plan does not match course"):
        MoodleTeachingPlanImportService(
            _Sessions(UFMGSession("private", 1, 999), []),
            _Client(),
            WrongTerm(),
            _Plans(),
            _Dates(),
        ).import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)


def test_import_deletes_expired_session_reported_by_moodle() -> None:
    class Expired(_Client):
        def fetch_diario_plan(self, token: str, *, term: str, source_id: int) -> dict[str, object]:
            raise UFMGReauthenticationRequired("expired")

    sessions = _Sessions(UFMGSession("private", 1, 999), [])
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleTeachingPlanImportService(
            sessions, Expired(), _Courses(), _Plans(), _Dates()
        ).import_plan("user-1", course_id="course-a", term="2026-2", source_id=701, now=123)
    assert sessions.deleted == ["user-1"]
