from datetime import UTC, datetime
from typing import Any

import pytest

from session_service import (
    InactiveAttendanceSession,
    InvalidSessionMutation,
    replace_attendance,
    replace_calendar_status,
)

NOW = datetime(2026, 10, 8, 18, 30, tzinfo=UTC)


def _session(**overrides: object) -> dict[str, Any]:
    return {
        "id": "2026-10-08--thursday-19",
        "starts_at": "2026-10-08T22:00:00Z",
        "ends_at": "2026-10-08T23:40:00Z",
        "lesson_count": 2,
        "call_count": 2,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": None,
        "absences": None,
        "calendar_status": "scheduled",
        "assessment_title": "Prova 1",
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
        **overrides,
    }


def test_initial_attendance_uses_the_canonical_default_and_preserves_other_fields() -> None:
    original = _session(first_ping="no_campus")

    updated = replace_attendance(original, {"status": "chegou_atrasado"}, now=NOW)

    assert updated == {
        **original,
        "attendance_status": "chegou_atrasado",
        "absences": 1,
        "updated_at": "2026-10-08T18:30:00Z",
    }


def test_manual_correction_replaces_status_and_absences_without_audit_history() -> None:
    updated = replace_attendance(
        _session(attendance_status="ausente", absences=2),
        {"status": "presente", "absences": 1},
        now=NOW,
    )

    assert updated["attendance_status"] == "presente"
    assert updated["absences"] == 1


def test_pending_correction_has_no_absences() -> None:
    updated = replace_attendance(
        _session(attendance_status="presente", absences=0),
        {"status": "pendente", "absences": None},
        now=NOW,
    )

    assert updated["attendance_status"] == "pendente"
    assert updated["absences"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "presente", "extra": 1},
        {"status": "desconhecido"},
        {"status": "pendente", "absences": 0},
        {"status": "presente", "absences": None},
        {"status": "presente", "absences": True},
        {"status": "presente", "absences": -1},
        {"status": "presente", "absences": 3},
    ],
)
def test_attendance_rejects_invalid_inputs_without_changing_the_source(
    payload: dict[str, object],
) -> None:
    original = _session()

    with pytest.raises(InvalidSessionMutation):
        replace_attendance(original, payload, now=NOW)

    assert original["attendance_status"] is None
    assert original["updated_at"] == "2026-08-01T12:00:00Z"


@pytest.mark.parametrize("calendar_status", ["cancelled", "holiday", "no_call"])
def test_attendance_rejects_sessions_that_do_not_require_a_call(
    calendar_status: str,
) -> None:
    with pytest.raises(InactiveAttendanceSession):
        replace_attendance(
            _session(calendar_status=calendar_status),
            {"status": "presente"},
            now=NOW,
        )


@pytest.mark.parametrize("calendar_status", ["scheduled", "cancelled", "holiday", "no_call"])
def test_calendar_status_replacement_preserves_attendance_and_assessment(
    calendar_status: str,
) -> None:
    original = _session(attendance_status="presente", absences=0)

    updated = replace_calendar_status(
        original,
        {"calendar_status": calendar_status},
        now=NOW,
    )

    assert updated == {
        **original,
        "calendar_status": calendar_status,
        "updated_at": "2026-10-08T18:30:00Z",
    }


@pytest.mark.parametrize(
    "payload",
    [{}, {"calendar_status": "makeup"}, {"calendar_status": "unknown"}, {"extra": 1}],
)
def test_calendar_status_rejects_invalid_replacements(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidSessionMutation):
        replace_calendar_status(_session(), payload, now=NOW)


def test_mutations_require_an_aware_server_timestamp() -> None:
    with pytest.raises(InvalidSessionMutation):
        replace_attendance(_session(), {"status": "presente"}, now=NOW.replace(tzinfo=None))
