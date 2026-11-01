from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_session_service import _session

from checkpoint_service import checkpoint_decision, validate_checkpoint_payload
from session_service import InvalidSessionMutation

NOW = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
START = 1791496800000
END = START + 6000000


def payload(first="no_campus", second="fora"):
    return {
        "starts_at_ms": START,
        "ends_at_ms": END,
        "lesson_count": 2,
        "call_count": 2,
        "campus_id": "pampulha",
        "first": {
            "operation_id": "first-id",
            "status": "succeeded",
            "ping": first,
            "expected_at_ms": START + 1200000,
            "captured_at_ms": START + 1200100,
        },
        "second": {
            "operation_id": "second-id",
            "status": "succeeded",
            "ping": second,
            "expected_at_ms": END - 1200000,
            "captured_at_ms": END - 1199900,
        },
    }


def test_uses_canonical_classification_and_keeps_other_session_fields():
    original = _session()
    snapshot = deepcopy(original)
    outcome, reason, updated = checkpoint_decision(original, payload(), now=NOW)
    assert (outcome, reason) == ("applied", "classified")
    assert updated["attendance_status"] == "saiu_mais_cedo" and updated["absences"] == 1
    assert updated["assessment_title"] == original["assessment_title"]
    assert original == snapshot
    assert checkpoint_decision(updated, payload(), now=NOW)[:2] == (
        "already_applied",
        "matching_evidence",
    )


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"attendance_status": "presente", "absences": 0}, "existing_attendance"),
        ({"first_ping": "fora"}, "existing_attendance"),
        ({"calendar_status": "cancelled"}, "session_without_roll_call"),
        ({"calendar_status": "no_call"}, "session_without_roll_call"),
        ({"call_count": 1}, "session_changed"),
        ({"starts_at": "2026-10-08T22:01:00Z"}, "session_changed"),
    ],
)
def test_preserves_manual_records_and_changed_sessions(changes, reason):
    assert checkpoint_decision(_session(**changes), payload(), now=NOW) == (
        "preserved",
        reason,
        None,
    )


def test_missing_failed_and_bad_quality_evidence_never_implies_absence():
    p = payload()
    p["second"] = None
    assert checkpoint_decision(_session(), p, now=NOW) == (
        "unresolved",
        "insufficient_evidence",
        None,
    )
    p = payload()
    p["second"]["status"] = "cancelled"
    assert checkpoint_decision(_session(), p, now=NOW)[0] == "unresolved"
    p = payload()
    p["second"]["captured_at_ms"] = END
    assert checkpoint_decision(_session(), p, now=NOW)[0] == "unresolved"
    p = payload()
    p["call_count"] = 1
    p["second"] = None
    assert checkpoint_decision(_session(call_count=1), p, now=NOW)[2]["absences"] == 0


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(extra=True),
        lambda p: p.update(lesson_count=True),
        lambda p: p.update(call_count=4),
        lambda p: p.update(campus_id="bad/id"),
        lambda p: p.update(starts_at_ms="yesterday"),
        lambda p: p.update(ends_at_ms=0),
        lambda p: p["first"].update(status="running"),
        lambda p: p["first"].update(ping="invalid"),
        lambda p: p["first"].update(operation_id="bad/id"),
        lambda p: p["first"].update(extra=True),
        lambda p: p["first"].update(expected_at_ms=True),
        lambda p: p.update(first=[]),
    ],
)
def test_rejects_invalid_payload_before_writes(change):
    p = payload()
    change(p)
    with pytest.raises(InvalidSessionMutation):
        validate_checkpoint_payload(p)


def test_one_lesson_cannot_have_two_calls_and_missing_window_stays_waiting():
    p = payload()
    p["lesson_count"] = 1
    with pytest.raises(InvalidSessionMutation):
        validate_checkpoint_payload(p)
    p = payload()
    p["second"] = None
    assert checkpoint_decision(_session(), p, now=datetime(2026, 10, 8, 22, 30, tzinfo=UTC)) == (
        "waiting",
        "checkpoint_window_open",
        None,
    )
