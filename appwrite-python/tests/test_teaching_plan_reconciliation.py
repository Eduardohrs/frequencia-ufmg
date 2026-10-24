from datetime import UTC, datetime

import pytest

from teaching_plan_reconciliation import (
    InvalidTeachingPlanReconciliation,
    reconcile_teaching_plan_schedule,
)

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def _row(day: str, start: str = "19:00", end: str = "20:40") -> dict[str, object]:
    return {
        "sequence": 1,
        "occurrence_key": f"{day}T{start}-{end}",
        "date": day,
        "weekday": "Seg",
        "lesson_count": 2,
        "starts_at": start,
        "ends_at": end,
        "kind": "Teórica",
        "subject": "Polimorfismo",
    }


def _session(
    identifier: str,
    starts_at: str,
    ends_at: str,
    *,
    attendance: str | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "lesson_count": 2,
        "call_count": 1,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": attendance,
        "absences": 0 if attendance else None,
        "calendar_status": "scheduled",
        "assessment_title": None,
        "created_at": "2026-08-01T12:00:00Z",
        "updated_at": "2026-08-01T12:00:00Z",
    }


def test_preview_matches_exact_occurrence_without_writes() -> None:
    result = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")],
        [_session("manual", "2026-08-10T22:00:00Z", "2026-08-10T23:40:00Z")],
        now=NOW,
    )

    assert result.counts["matched"] == 1
    assert result.counts["missing"] == 0
    assert result.counts["conflicting"] == 0
    assert result.creates == ()
    assert result.conflicts == ()


def test_preview_creates_only_a_truly_missing_occurrence() -> None:
    result = reconcile_teaching_plan_schedule([_row("2026-08-10")], [], now=NOW)

    assert result.counts["matched"] == 0
    assert result.counts["missing"] == 1
    assert result.counts["conflicting"] == 0
    assert result.creates[0]["id"] == "2026-08-10--diario-1900-2040"
    assert result.creates[0]["starts_at"] == "2026-08-10T22:00:00Z"
    assert result.creates[0]["ends_at"] == "2026-08-10T23:40:00Z"
    assert result.creates[0]["attendance_status"] is None


def test_preview_reports_overlap_and_never_overwrites_attendance() -> None:
    existing = _session(
        "existing",
        "2026-08-10T22:30:00Z",
        "2026-08-11T00:10:00Z",
        attendance="presente",
    )

    result = reconcile_teaching_plan_schedule([_row("2026-08-10")], [existing], now=NOW)

    assert result.counts["matched"] == 0
    assert result.counts["missing"] == 0
    assert result.counts["conflicting"] == 1
    assert result.creates == ()
    assert result.conflicts == (
        {
            "occurrence_key": "2026-08-10T19:00-20:40",
            "reason": "overlapping_session",
            "existing_session_ids": ["existing"],
        },
    )
    assert existing["attendance_status"] == "presente"


def test_preview_is_idempotent_after_applying_its_create() -> None:
    first = reconcile_teaching_plan_schedule([_row("2026-08-10")], [], now=NOW)
    second = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")], list(first.creates), now=NOW
    )

    assert second.counts["matched"] == 1
    assert second.counts["missing"] == 0
    assert second.counts["conflicting"] == 0
    assert second.creates == ()


def test_reconciliation_links_assessment_to_matching_existing_session() -> None:
    existing = _session("existing", "2026-08-10T22:00:00Z", "2026-08-10T23:40:00Z")
    result = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")],
        [existing],
        assessments=[{
            "code": "AV1",
            "kind": "PROVA",
            "title": "Primeira prova",
            "scheduled_at": "2026-08-10T19:30:00-03:00",
            "location": "Sala 1",
            "value": "30.00",
            "weight": "1.00",
        }],
        now=NOW,
    )

    assert result.updates[0]["id"] == "existing"
    assert result.updates[0]["assessment_title"] == "Primeira prova"
    assert result.updates[0]["attendance_status"] is None
    assert result.counts["assessments_linked"] == 1


def test_reconciliation_preserves_divergent_manual_assessment() -> None:
    existing = _session("existing", "2026-08-10T22:00:00Z", "2026-08-10T23:40:00Z")
    existing["assessment_title"] = "Título corrigido"
    result = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")],
        [existing],
        assessments=[{
            "code": "AV1",
            "kind": "PROVA",
            "title": "Primeira prova",
            "scheduled_at": "2026-08-10T19:30:00-03:00",
            "location": "Sala 1",
            "value": "30.00",
            "weight": "1.00",
        }],
        now=NOW,
    )

    assert result.updates == ()
    assert result.counts["assessment_conflicts"] == 1
    assert result.conflicts[-1]["reason"] == "assessment_title_mismatch"


def test_reconciliation_keeps_equal_assessment_and_links_new_session() -> None:
    assessment = {
        "title": "Primeira prova",
        "scheduled_at": "2026-08-10T19:30:00-03:00",
    }
    existing = _session("existing", "2026-08-10T22:00:00Z", "2026-08-10T23:40:00Z")
    existing["assessment_title"] = "Primeira prova"
    equal = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")], [existing], assessments=[assessment], now=NOW
    )
    created = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")], [], assessments=[assessment], now=NOW
    )

    assert equal.updates == ()
    assert equal.counts["assessment_conflicts"] == 0
    assert created.creates[0]["assessment_title"] == "Primeira prova"
    assert created.counts["assessments_linked"] == 1


@pytest.mark.parametrize(
    "assessments",
    ["invalid", [1], [{}], [{"title": "Prova", "scheduled_at": "invalid"}]],
)
def test_reconciliation_rejects_invalid_assessments(assessments: object) -> None:
    with pytest.raises(InvalidTeachingPlanReconciliation, match="assessment"):
        reconcile_teaching_plan_schedule(
            [_row("2026-08-10")], [], assessments=assessments, now=NOW
        )


def test_reconciliation_leaves_assessment_outside_class_as_standalone() -> None:
    result = reconcile_teaching_plan_schedule(
        [_row("2026-08-10")],
        [],
        assessments=[{
            "title": "Trabalho",
            "scheduled_at": "2026-08-11T19:30:00-03:00",
        }],
        now=NOW,
    )

    assert result.creates[0]["assessment_title"] is None
    assert result.counts["assessments_linked"] == 0


def test_reconciliation_rejects_invalid_saved_sessions_and_clock() -> None:
    invalid = _session("broken", "2026-08-10T22:00:00Z", "2026-08-10T23:40:00Z")
    invalid.pop("first_ping")
    with pytest.raises(InvalidTeachingPlanReconciliation, match="invalid saved session"):
        reconcile_teaching_plan_schedule([], [invalid], now=NOW)
    with pytest.raises(InvalidTeachingPlanReconciliation, match="invalid clock"):
        reconcile_teaching_plan_schedule([], [], now=datetime(2026, 10, 24, 12))


@pytest.mark.parametrize(
    "schedule",
    [
        "invalid",
        [_row("2026-08-10")] * 451,
        [{}],
        [{**_row("2026-08-10"), "lesson_count": 3}],
        [{**_row("2026-08-10"), "ends_at": "20:00", "occurrence_key": "2026-08-10T19:00-20:00"}],
        [{**_row("2026-08-10"), "occurrence_key": "wrong"}],
        [{**_row("2019-08-10"), "occurrence_key": "2019-08-10T19:00-20:40"}],
    ],
)
def test_reconciliation_rejects_invalid_occurrences(schedule: object) -> None:
    with pytest.raises(InvalidTeachingPlanReconciliation):
        reconcile_teaching_plan_schedule(schedule, [], now=NOW)


def test_reconciliation_rejects_duplicate_occurrence_keys() -> None:
    with pytest.raises(InvalidTeachingPlanReconciliation, match="duplicate"):
        reconcile_teaching_plan_schedule(
            [_row("2026-08-10"), _row("2026-08-10")], [], now=NOW
        )
