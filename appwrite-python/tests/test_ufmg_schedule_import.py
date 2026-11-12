from typing import Any

import pytest

from schedule_repository import DestructiveScheduleChange
from schedule_service import ScheduleOverlap
from ufmg_schedule_import import UFMGScheduleImportService, _default_dates, _is_imported
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


def _remote(
    *,
    code: str = "ELE028",
    term: str = "2026-2",
    start: int = 450,
) -> dict[str, object]:
    return {
        "code": code,
        "name": code,
        "workload": 30,
        "term": term,
        "starts_on": "2026-08-03T00:00:00Z",
        "ends_on": "2026-12-05T00:00:00Z",
        "meetings": [{"weekday": 1, "start_minutes": start, "lesson_count": 2}],
    }


def _course(*, course_id: str = "ele028", term: str = "2026-2") -> dict[str, object]:
    return {
        "id": course_id,
        "code": "ELE028",
        "term": term,
        "starts_on": None,
        "ends_on": None,
    }


def _saved_meeting(
    meeting_id: str, *, weekday: int = 1, start: int = 450, call_count: int = 1
) -> dict[str, object]:
    return {
        "id": meeting_id,
        "weekday": weekday,
        "start_minutes": start,
        "end_minutes": start + 100,
        "lesson_count": 2,
        "call_count": call_count,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }


class _Sessions:
    def __init__(self, session: UFMGSession | None = None) -> None:
        self.session = session or UFMGSession("private-token", 1, 99)
        self.deleted = False

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        assert user_id == "user"
        assert now == 10
        return self.session

    def delete(self, user_id: str) -> None:
        assert user_id == "user"
        self.deleted = True


class _Enrollments:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values

    def fetch(self, token: str) -> list[dict[str, object]]:
        assert token == "private-token"
        return self.values


class _Courses:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values

    def list_courses(self) -> list[dict[str, Any]]:
        return self.values


class _Schedules:
    def __init__(
        self,
        states: dict[str, dict[str, Any]],
        failure: Exception | None = None,
    ) -> None:
        self.states = states
        self.failure = failure
        self.saved: list[tuple[str, dict[str, object]]] = []

    def load_import_schedules(self, courses: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        assert {str(course["id"]) for course in courses} == set(self.states)
        return self.states

    def save_import_schedule(
        self,
        course_id: str,
        payload: dict[str, object],
        schedules: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        assert schedules is self.states
        if self.failure is not None:
            raise self.failure
        self.saved.append((course_id, payload))
        return {
            **self.states[course_id],
            "changes": {
                "meeting_upserts": len(payload["meetings"]),
                "meeting_deletes": 0,
                "session_upserts": 0,
                "session_deletes": 0,
            },
        }


def _state(course: dict[str, object], meetings: list[dict[str, object]]) -> dict[str, Any]:
    return {"course": course, "meetings": meetings, "changes": {}}


def _service(
    remote: list[dict[str, object]],
    courses: list[dict[str, object]],
    schedules: _Schedules,
    sessions: _Sessions | None = None,
) -> UFMGScheduleImportService:
    return UFMGScheduleImportService(
        sessions or _Sessions(), _Enrollments(remote), _Courses(courses), schedules
    )


def test_imports_new_schedule_with_remote_dates_and_one_call() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [])})

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result == {
        "total": 1,
        "updated": 1,
        "unchanged": 0,
        "conflicts": 0,
        "missing_courses": 0,
        "meetings_imported": 1,
        "date_mismatches": 1,
        "meeting_mismatches": 1,
        "meeting_upserts": 1,
        "meeting_deletes": 0,
        "session_upserts": 0,
        "session_deletes": 0,
        "pendencies_created": 0,
    }
    assert schedules.saved == [
        (
            "ele028",
            {
                "starts_on": "2026-08-03T00:00:00Z",
                "ends_on": "2026-12-05T00:00:00Z",
                "meetings": [
                    {
                        "id": "ufmg-1-450-2",
                        "weekday": 1,
                        "start_minutes": 450,
                        "lesson_count": 2,
                        "call_count": 1,
                    }
                ],
                "confirm_destructive": False,
            },
        )
    ]


def test_online_course_keeps_manual_policy_and_never_imports_schedule() -> None:
    course = {**_course(), "modality": "online", "attendance_policy": "no_call"}
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual")])})
    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)
    assert result["unchanged"] == 1
    assert schedules.saved == []
    assert course["modality"] == "online"


def test_preserves_equivalent_manual_schedule_and_custom_dates() -> None:
    course = {
        **_course(),
        "starts_on": "2026-09-01T00:00:00Z",
        "ends_on": "2026-11-30T00:00:00Z",
    }
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", call_count=2)])})

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["unchanged"] == 1
    assert result["meetings_imported"] == 0
    assert schedules.saved == []


def test_preserves_manual_schedule_when_remote_differs() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", start=500)])})

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert schedules.saved == []


def test_treats_a_manually_edited_imported_slot_as_user_owned() -> None:
    course = _course()
    schedules = _Schedules(
        {
            "ele028": _state(
                course,
                [_saved_meeting("ufmg-1-450-2", start=500)],
            )
        }
    )

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert schedules.saved == []


def test_reconciles_only_managed_meetings_and_preserves_call_count() -> None:
    course = {
        **_course(),
        "starts_on": "2026-07-01T00:00:00Z",
        "ends_on": "2026-12-31T00:00:00Z",
    }
    schedules = _Schedules(
        {
            "ele028": _state(
                course,
                [
                    _saved_meeting("ufmg-1-450-2", call_count=2),
                    _saved_meeting("ufmg-3-600-2", weekday=3, start=600),
                ],
            )
        }
    )

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["updated"] == 1
    payload = schedules.saved[0][1]
    assert payload["meetings"] == [
        {
            "id": "ufmg-1-450-2",
            "weekday": 1,
            "start_minutes": 450,
            "lesson_count": 2,
            "call_count": 2,
        }
    ]
    assert payload["starts_on"] == "2026-08-03T00:00:00Z"


@pytest.mark.parametrize("failure", [DestructiveScheduleChange(1), ScheduleOverlap("overlap")])
def test_reports_safe_conflict_instead_of_overwriting(failure: Exception) -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [])}, failure)

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert result["updated"] == 0


def test_matches_code_and_term_and_reports_missing_course() -> None:
    old = _course(course_id="old", term="2026-1")
    current = _course(course_id="current")
    schedules = _Schedules({"old": _state(old, []), "current": _state(current, [])})

    result = _service(
        [_remote(), _remote(code="MAT001")], [old, current], schedules
    ).import_schedules("user", now=10)

    assert schedules.saved[0][0] == "current"
    assert result["missing_courses"] == 1
    assert result["total"] == 2


def test_is_idempotent_when_managed_schedule_already_matches() -> None:
    course = {
        **_course(),
        "starts_on": "2026-08-03T00:00:00Z",
        "ends_on": "2026-12-05T00:00:00Z",
    }
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("ufmg-1-450-2")])})

    result = _service([_remote()], [course], schedules).import_schedules("user", now=10)

    assert result["unchanged"] == 1
    assert schedules.saved == []


def test_requires_live_session_and_deletes_rejected_session() -> None:
    missing = _Sessions()
    missing.session = None
    with pytest.raises(UFMGReauthenticationRequired):
        _service([], [], _Schedules({}), missing).import_schedules("user", now=10)

    class _Expired(_Enrollments):
        def fetch(self, token: str) -> list[dict[str, object]]:
            raise UFMGReauthenticationRequired

    sessions = _Sessions()
    service = UFMGScheduleImportService(sessions, _Expired([]), _Courses([]), _Schedules({}))
    with pytest.raises(UFMGReauthenticationRequired):
        service.import_schedules("user", now=10)
    assert sessions.deleted


def test_rejects_invalid_repository_or_remote_shape() -> None:
    course = _course()
    for state, remote in (
        ({"course": None, "meetings": [], "changes": {}}, _remote()),
        (_state(course, []), {**_remote(), "meetings": None}),
        (_state(course, []), {**_remote(), "meetings": [None]}),
    ):
        service = _service([remote], [course], _Schedules({"ele028": state}))
        with pytest.raises(ValueError):
            service.import_schedules("user", now=10)


def test_small_helpers_cover_manual_and_first_semester_contracts() -> None:
    assert not _is_imported(None)
    assert not _is_imported({"id": "ufmg-incomplete"})
    assert _default_dates("2026-1") == (
        "2026-01-01T00:00:00Z",
        "2026-06-30T00:00:00Z",
    )


class _Pendencies:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.saved: list[dict[str, Any]] = []

    def list_pendencies(
        self,
        user_id: str,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            item
            for item in self.existing
            if item.get("user_id", "user") == user_id
            and (course_id is None or item.get("course_id") == course_id)
        ]

    def save_pendency(self, **kwargs: Any) -> str:
        self.saved.append(kwargs)
        return f"pend-{len(self.saved)}"


def _service_with_pendencies(
    remote: list[dict[str, object]],
    courses: list[dict[str, object]],
    schedules: _Schedules,
    pendencies: _Pendencies | None,
) -> UFMGScheduleImportService:
    return UFMGScheduleImportService(
        _Sessions(), _Enrollments(remote), _Courses(courses), schedules, pendencies
    )


def test_manual_divergence_creates_persisted_pendency_with_context() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", start=500)])})
    pendencies = _Pendencies()

    result = _service_with_pendencies(
        [_remote()], [course], schedules, pendencies
    ).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert result["pendencies_created"] == 1
    assert len(pendencies.saved) == 1
    saved = pendencies.saved[0]
    assert saved["user_id"] == "user"
    assert saved["course_id"] == "ele028"
    assert saved["course_code"] == "ELE028"
    assert saved["reason"] == "manual_schedule_diverged"
    assert "seg 08:20" in saved["current_schedule"]  # 500 minutes = 08:20
    assert "seg 07:30" in saved["new_schedule"]  # 450 minutes = 07:30
    # the stored payload never pre-authorizes destructive deletion; applying a
    # pendency goes through the safe flow with confirm_destructive=False
    assert saved["payload"]["confirm_destructive"] is False
    assert saved["payload"]["meetings"][0]["id"] == "ufmg-1-450-2"


def test_identical_source_does_not_recreate_pendency() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", start=500)])})
    new_schedule = "seg 07:30 (2 aulas)"
    pendencies = _Pendencies(
        existing=[
            {
                "user_id": "user",
                "course_id": "ele028",
                "new_schedule": new_schedule,
                "status": "resolved",
            }
        ]
    )

    result = _service_with_pendencies(
        [_remote()], [course], schedules, pendencies
    ).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert result["pendencies_created"] == 0
    assert pendencies.saved == []


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (DestructiveScheduleChange(1), "destructive_change"),
        (ScheduleOverlap("overlap"), "schedule_overlap"),
    ],
)
def test_safe_conflict_creates_pendency_with_reason(failure: Exception, reason: str) -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [])}, failure)
    pendencies = _Pendencies()

    result = _service_with_pendencies(
        [_remote()], [course], schedules, pendencies
    ).import_schedules("user", now=10)

    assert result["conflicts"] == 1
    assert result["pendencies_created"] == 1
    assert pendencies.saved[0]["reason"] == reason


def test_conflict_without_pendency_sink_still_counts_conflict() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", start=500)])})

    result = _service_with_pendencies([_remote()], [course], schedules, None).import_schedules(
        "user", now=10
    )

    assert result["conflicts"] == 1
    assert result["pendencies_created"] == 0


def test_schedule_summary_handles_invalid_and_out_of_range_weekday() -> None:
    from ufmg_schedule_import import _schedule_summary

    assert _schedule_summary([]) == ""
    assert _schedule_summary(["not-a-mapping"]) == ""
    summary = _schedule_summary([{"weekday": 9, "start_minutes": 480, "lesson_count": 4}])
    assert summary == "9 08:00 (4 aulas)"


def test_pendency_created_when_existing_entries_do_not_match() -> None:
    course = _course()
    schedules = _Schedules({"ele028": _state(course, [_saved_meeting("manual", start=500)])})
    pendencies = _Pendencies(
        existing=[{"user_id": "user", "course_id": "ele028", "new_schedule": "qua 10:00 (2 aulas)"}]
    )

    result = _service_with_pendencies(
        [_remote()], [course], schedules, pendencies
    ).import_schedules("user", now=10)

    assert result["pendencies_created"] == 1
    assert len(pendencies.saved) == 1
