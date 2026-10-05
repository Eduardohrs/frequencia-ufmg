from datetime import UTC, datetime

import pytest

import schedule_service as module
from schedule_service import (
    InvalidSchedule,
    ScheduleOverlap,
    SchedulePlan,
    build_schedule_plan,
    validate_saved_meeting,
    validate_saved_session,
)

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _course(
    course_id: str = "poo",
    *,
    term: str = "2026-2",
    starts_on: str | None = "2026-08-04T00:00:00Z",
    ends_on: str | None = "2026-12-03T00:00:00Z",
) -> dict[str, object]:
    return {
        "id": course_id,
        "code": course_id.upper(),
        "name": course_id,
        "workload": 1,
        "term": term,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _meeting_input(
    meeting_id: str = "tuesday-19",
    *,
    weekday: int = 2,
    start_minutes: int = 19 * 60,
    lesson_count: int = 2,
    call_count: int = 1,
) -> dict[str, object]:
    return {
        "id": meeting_id,
        "weekday": weekday,
        "start_minutes": start_minutes,
        "lesson_count": lesson_count,
        "call_count": call_count,
    }


def _meeting(
    meeting_id: str = "tuesday-19",
    *,
    weekday: int = 2,
    start_minutes: int = 19 * 60,
    lesson_count: int = 2,
    call_count: int = 1,
) -> dict[str, object]:
    return {
        **_meeting_input(
            meeting_id,
            weekday=weekday,
            start_minutes=start_minutes,
            lesson_count=lesson_count,
            call_count=call_count,
        ),
        "end_minutes": start_minutes + lesson_count * 50,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _session(
    session_id: str,
    *,
    starts_at: str,
    ends_at: str,
    attendance_status: str | None = None,
    absences: int | None = None,
    calendar_status: str = "scheduled",
    assessment_title: str | None = None,
) -> dict[str, object]:
    return {
        "id": session_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "lesson_count": 2,
        "call_count": 1,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": attendance_status,
        "absences": absences,
        "calendar_status": calendar_status,
        "assessment_title": assessment_title,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def _plan(
    *,
    course: dict[str, object] | None = None,
    requested_meetings: object = None,
    existing_meetings: list[dict[str, object]] | None = None,
    existing_sessions: list[dict[str, object]] | None = None,
    other_schedules: list[tuple[dict[str, object], list[dict[str, object]]]] | None = None,
    starts_on: object = "2026-08-04T00:00:00Z",
    ends_on: object = "2026-12-03T00:00:00Z",
) -> SchedulePlan:
    return build_schedule_plan(
        course=course or _course(),
        requested_starts_on=starts_on,
        requested_ends_on=ends_on,
        requested_meetings=[_meeting_input()] if requested_meetings is None else requested_meetings,
        existing_meetings=existing_meetings or [],
        existing_sessions=existing_sessions or [],
        other_schedules=other_schedules or [],
        now=NOW,
    )


def test_schedule_generates_retroactive_sessions_and_is_idempotent() -> None:
    first = _plan(
        starts_on="2026-08-04T00:00:00Z",
        ends_on="2026-08-18T00:00:00Z",
    )

    assert [item["id"] for item in first.session_upserts] == [
        "2026-08-04--tuesday-19",
        "2026-08-11--tuesday-19",
        "2026-08-18--tuesday-19",
    ]
    assert first.meeting_delete_ids == ()
    assert first.session_delete_ids == ()

    second = _plan(
        starts_on="2026-08-04T00:00:00Z",
        ends_on="2026-08-18T00:00:00Z",
        existing_meetings=list(first.meetings),
        existing_sessions=list(first.session_upserts),
    )

    assert second.meeting_upserts == ()
    assert second.session_upserts == ()
    assert second.session_delete_ids == ()
    assert second.destructive_delete_count == 0


def test_schedule_preserves_evidence_exceptions_and_assessments() -> None:
    sessions = [
        _session(
            "2026-08-04--tuesday-19",
            starts_at="2026-08-04T22:00:00Z",
            ends_at="2026-08-04T23:40:00Z",
            attendance_status="presente",
            absences=0,
        ),
        _session(
            "2026-08-11--tuesday-19",
            starts_at="2026-08-11T22:00:00Z",
            ends_at="2026-08-11T23:40:00Z",
            calendar_status="cancelled",
        ),
        _session(
            "2026-08-18--tuesday-19",
            starts_at="2026-08-18T22:00:00Z",
            ends_at="2026-08-18T23:40:00Z",
            assessment_title="Prova 1",
        ),
    ]

    plan = _plan(
        starts_on="2026-09-01T00:00:00Z",
        ends_on="2026-09-01T00:00:00Z",
        existing_meetings=[_meeting()],
        existing_sessions=sessions,
    )

    assert plan.session_delete_ids == tuple(item["id"] for item in sessions)
    assert plan.destructive_delete_count == 3


def test_schedule_rejects_partial_overlap_in_same_or_other_course() -> None:
    with pytest.raises(ScheduleOverlap):
        _plan(
            requested_meetings=[
                _meeting_input("first", start_minutes=7 * 60),
                _meeting_input("second", start_minutes=7 * 60 + 30),
            ]
        )

    with pytest.raises(ScheduleOverlap):
        _plan(
            requested_meetings=[_meeting_input("first", start_minutes=7 * 60)],
            other_schedules=[
                (
                    _course("other"),
                    [_meeting("other-slot", start_minutes=7 * 60 + 30)],
                )
            ],
        )


def test_schedule_allows_same_slot_when_course_periods_do_not_intersect() -> None:
    plan = _plan(
        other_schedules=[
            (
                _course(
                    "next",
                    term="2027-1",
                    starts_on="2027-01-01T00:00:00Z",
                    ends_on="2027-06-30T00:00:00Z",
                ),
                [_meeting("next-slot")],
            )
        ]
    )

    assert len(plan.meetings) == 1


@pytest.mark.parametrize(
    ("course", "starts_on", "ends_on", "requested_meetings"),
    [
        (_course(term="2026-1"), "2026-01-01T00:00:00Z", "2026-06-30T00:00:00Z", []),
        (_course(term="2028-1"), "2028-01-01T00:00:00Z", "2028-06-30T00:00:00Z", []),
        (_course(), "2026-06-30T00:00:00Z", "2026-08-01T00:00:00Z", []),
        (_course(), None, "2026-12-03T00:00:00Z", []),
        (_course(), None, None, [_meeting_input()]),
    ],
)
def test_schedule_rejects_disallowed_or_contradictory_periods(
    course: dict[str, object],
    starts_on: object,
    ends_on: object,
    requested_meetings: object,
) -> None:
    with pytest.raises(InvalidSchedule):
        _plan(
            course=course,
            starts_on=starts_on,
            ends_on=ends_on,
            requested_meetings=requested_meetings,
        )


@pytest.mark.parametrize(
    "meeting",
    [
        {**_meeting_input(), "extra": True},
        {**_meeting_input(), "id": "bad/id"},
        {**_meeting_input(), "weekday": 0},
        {**_meeting_input(), "start_minutes": -1},
        {**_meeting_input(), "start_minutes": 23 * 60 + 30, "lesson_count": 2},
        {**_meeting_input(), "lesson_count": 3},
        {**_meeting_input(), "lesson_count": 1, "call_count": 2},
    ],
)
def test_schedule_rejects_invalid_meetings(meeting: dict[str, object]) -> None:
    with pytest.raises(InvalidSchedule):
        _plan(requested_meetings=[meeting])


def test_schedule_updates_changed_unevidenced_session_and_preserves_metadata() -> None:
    saved = _session(
        "2026-08-04--tuesday-19",
        starts_at="2026-08-04T21:00:00Z",
        ends_at="2026-08-04T22:40:00Z",
        calendar_status="holiday",
        assessment_title="Prova",
    )

    plan = _plan(
        starts_on="2026-08-04T00:00:00Z",
        ends_on="2026-08-04T00:00:00Z",
        existing_sessions=[saved],
    )

    assert plan.session_upserts[0]["starts_at"] == "2026-08-04T22:00:00Z"
    assert plan.session_upserts[0]["calendar_status"] == "holiday"
    assert plan.session_upserts[0]["assessment_title"] == "Prova"


def test_schedule_checks_active_other_course_without_explicit_period() -> None:
    other = _course("other", starts_on=None, ends_on=None)
    plan = _plan(
        requested_meetings=[_meeting_input(start_minutes=8 * 60)],
        other_schedules=[(other, [_meeting("other", start_minutes=10 * 60)])],
    )

    assert len(plan.meetings) == 1


def test_schedule_rejects_invalid_course_duplicate_saved_ids_and_invalid_other_course() -> None:
    invalid_course = {**_course(), "code": "lower"}
    with pytest.raises(InvalidSchedule):
        _plan(course=invalid_course)
    with pytest.raises(InvalidSchedule):
        _plan(existing_meetings=[_meeting(), _meeting()])
    with pytest.raises(InvalidSchedule):
        _plan(other_schedules=[(invalid_course, [])])


def test_schedule_rejects_duplicate_requested_ids_and_unbounded_inputs() -> None:
    with pytest.raises(InvalidSchedule):
        _plan(requested_meetings="not-a-list")
    with pytest.raises(InvalidSchedule):
        _plan(requested_meetings=[_meeting_input()] * 33)
    with pytest.raises(InvalidSchedule):
        _plan(requested_meetings=[_meeting_input(), _meeting_input()])


def test_schedule_rejects_non_midnight_period_and_naive_clock() -> None:
    with pytest.raises(InvalidSchedule):
        _plan(starts_on="2026-08-04T00:01:00Z")
    with pytest.raises(InvalidSchedule):
        build_schedule_plan(
            course=_course(),
            requested_starts_on=None,
            requested_ends_on=None,
            requested_meetings=[],
            existing_meetings=[],
            existing_sessions=[],
            other_schedules=[],
            now=datetime(2026, 10, 5, 12),
        )


def test_schedule_caps_generated_sessions() -> None:
    meetings = [
        _meeting_input(
            f"meeting-{weekday}-{slot}",
            weekday=weekday,
            start_minutes=slot * 100,
            lesson_count=2,
        )
        for weekday in range(1, 8)
        for slot in range(4)
    ]

    with pytest.raises(InvalidSchedule):
        _plan(
            requested_meetings=meetings,
            starts_on="2026-07-01T00:00:00Z",
            ends_on="2026-12-31T00:00:00Z",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("weekday"),
        lambda value: value.update(end_minutes=1),
        lambda value: value.update(updated_at="2026-07-01T00:00:00Z"),
    ],
)
def test_saved_meeting_validation_rejects_bad_schema(mutation: object) -> None:
    value = _meeting()
    mutation(value)  # type: ignore[operator]
    with pytest.raises(InvalidSchedule):
        validate_saved_meeting(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("first_ping"),
        lambda value: value.update(ends_at=value["starts_at"]),
        lambda value: value.update(absences=1),
        lambda value: value.update(attendance_status="presente", absences=3),
        lambda value: value.update(calendar_status="invalid"),
        lambda value: value.update(assessment_title=""),
        lambda value: value.update(updated_at="2026-07-01T00:00:00Z"),
    ],
)
def test_saved_session_validation_rejects_bad_schema(mutation: object) -> None:
    value = _session(
        "session",
        starts_at="2026-08-04T22:00:00Z",
        ends_at="2026-08-04T23:40:00Z",
    )
    mutation(value)  # type: ignore[operator]
    with pytest.raises(InvalidSchedule):
        validate_saved_session(value)


@pytest.mark.parametrize("term", ["bad", "2026-3"])
def test_term_date_parser_rejects_invalid_terms(term: str) -> None:
    with pytest.raises(InvalidSchedule):
        module._term_dates(term)


def test_first_semester_term_dates_are_supported() -> None:
    assert module._term_dates("2026-1") == (
        datetime(2026, 1, 1).date(),
        datetime(2026, 6, 30).date(),
    )


@pytest.mark.parametrize(
    "value",
    [3, "x" * 41, "not-a-date", "2026-08-01T00:00:00"],
)
def test_saved_timestamp_validation_rejects_invalid_instants(value: object) -> None:
    meeting = _meeting()
    meeting["created_at"] = value
    with pytest.raises(InvalidSchedule):
        validate_saved_meeting(meeting)
