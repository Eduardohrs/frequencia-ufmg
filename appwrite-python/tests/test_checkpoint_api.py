import json

import pytest
from test_checkpoint_service import payload
from test_main import FakeContext, FakeRequest

import main as function
from firestore_rest import FirestoreConflict

PATH = "/v1/courses/poo/sessions/s/checkpoints"


class Repo:
    def apply_checkpoints(self, course, session, body):
        assert (course, session) == ("poo", "s") and body == payload()
        return {
            "outcome": "applied",
            "reason": "classified",
            "status": "saiu_mais_cedo",
            "absences": 1,
            "first_operation_id": "first-id",
            "second_operation_id": "second-id",
        }


def test_route_authenticates_applies_and_logs_both_operations(monkeypatch):
    routes = []
    monkeypatch.setattr(
        function, "_authentication", lambda c, o, r: (routes.append(r) or "u", None)
    )
    monkeypatch.setattr(function, "_session_repository", lambda *_: Repo())
    monkeypatch.setenv("ENABLE_SESSION_WRITES", "true")
    c = FakeContext(FakeRequest("PUT", PATH, body_json=payload()))
    result = function.main(c)
    assert result["status"] == 200 and result["body"]["outcome"] == "applied"
    assert routes == ["/v1/sessions/checkpoints/put"]
    events = [json.loads(v) for v in c.logs]
    done = next(e for e in events if e["event"] == "checkpoint_delivery_succeeded")
    assert done["course_id"] == "poo" and done["session_id"] == "s"
    assert done["first_operation_id"] == "first-id" and done["second_operation_id"] == "second-id"
    assert "duration_ms" in done


def test_racing_edit_returns_retryable_conflict_and_a_diagnostic(monkeypatch):
    class Racing(Repo):
        def apply_checkpoints(self, *_):
            raise FirestoreConflict("changed")

    monkeypatch.setattr(function, "_authentication", lambda *_: ("u", None))
    monkeypatch.setattr(function, "_session_repository", lambda *_: Racing())
    monkeypatch.setenv("ENABLE_SESSION_WRITES", "true")
    c = FakeContext(FakeRequest("PUT", PATH, body_json=payload()))
    result = function.main(c)
    assert result["status"] == 409 and result["body"]["error"] == "checkpoint_conflict"
    assert any(json.loads(e)["event"] == "checkpoint_conflict" for e in c.errors)


@pytest.mark.parametrize(
    "failure,status,error",
    [
        ("missing", 404, "session_not_found"),
        ("denied", 403, "session_access_denied"),
        ("unavailable", 503, "session_store_unavailable"),
        ("invalid", 500, "session_data_invalid"),
        ("rejected_store", 500, "session_data_invalid"),
        ("bad", 400, "checkpoint_rejected"),
    ],
)
def test_failures_have_a_stage_and_safe_context(monkeypatch, failure, status, error):
    from firestore_rest import (
        FirestoreAccessDenied,
        FirestoreNotFound,
        FirestoreRequestRejected,
        FirestoreUnavailable,
    )
    from schedule_service import InvalidSchedule
    from session_service import InvalidSessionMutation

    failures = {
        "missing": FirestoreNotFound(),
        "denied": FirestoreAccessDenied(),
        "unavailable": FirestoreUnavailable(),
        "invalid": InvalidSchedule(),
        "rejected_store": FirestoreRequestRejected(),
        "bad": InvalidSessionMutation(),
    }

    class Broken(Repo):
        def apply_checkpoints(self, *_):
            raise failures[failure]

    monkeypatch.setattr(function, "_authentication", lambda *_: ("u", None))
    monkeypatch.setattr(function, "_session_repository", lambda *_: Broken())
    monkeypatch.setenv("ENABLE_SESSION_WRITES", "true")
    c = FakeContext(FakeRequest("PUT", PATH, body_json=payload()))
    result = function.main(c)
    assert result["status"] == status and result["body"] == {"error": error}
    record = json.loads(c.errors[-1])
    assert record["event"] == error and record["stage"] == "conditional_apply"
    assert record["first_operation_id"] == "first-id" and "duration_ms" in record


def test_authentication_and_write_switch_precede_checkpoint_repository(monkeypatch):
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("PUT", PATH))) is rejection
    monkeypatch.setattr(function, "_authentication", lambda *_: ("u", None))
    monkeypatch.delenv("ENABLE_SESSION_WRITES", raising=False)
    assert function.main(FakeContext(FakeRequest("PUT", PATH)))["status"] == 503
    monkeypatch.setenv("ENABLE_SESSION_WRITES", "true")
    c = FakeContext(FakeRequest("PUT", PATH, body_json={"password": "never-log-this"}))
    assert function.main(c)["status"] == 400
    assert "never-log-this" not in str(c.logs + c.errors)
