import json
from types import SimpleNamespace

import pytest
from test_main import FakeContext, FakeRequest

import main as function
from academic_date_repository import InvalidAcademicDate
from course_activities import CourseMoodleNotLinked
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreUnavailable,
)
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable
from teaching_plan_repository import InvalidTeachingPlan, TeachingPlanNotFound
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSessionStoreUnavailable


@pytest.fixture
def workspace(monkeypatch):
    from test_academic_date_repository import _Firestore

    store = _Firestore()
    courses = SimpleNamespace(
        get_course=lambda identifier: {"id": identifier, "code": "ELE631", "term": "2026-2"}
    )
    plan = SimpleNamespace(
        load=lambda identifier: {"plan": {"criteria": [], "schedule": [], "assessments": []}}
    )
    activities = SimpleNamespace(
        list_activities=lambda *args, **kwargs: {"activities": []},
        detail=lambda *args, **kwargs: {"description": "Task"},
        authorize_saved=lambda user, course, entry, **kwargs: entry,
    )
    snapshot = {
        "course_id": "poo",
        "term": "2026-2",
        "synced_at": "2026-10-28T12:00:00Z",
        "activities": [{"source_id": "20", "description": "Task", "files": []}],
    }
    monkeypatch.setattr(
        function, "ActivitySnapshotRepository", lambda _: SimpleNamespace(load=lambda _: snapshot)
    )
    monkeypatch.setattr(function, "_authentication", lambda *_: ("owner", None))
    monkeypatch.setattr(function, "_course_repository", lambda *_: courses)
    monkeypatch.setattr(function, "_firestore", lambda *_: store)
    monkeypatch.setattr(function, "TeachingPlanRepository", lambda *_: plan)
    monkeypatch.setattr(function, "_ufmg_session_store", lambda *_: None)
    monkeypatch.setattr(function, "_moodle_token_store", lambda *_: None)
    monkeypatch.setattr(function, "CourseActivityService", lambda *args, **kwargs: activities)
    return store, courses, plan, activities


def test_workspace_date_crud_plan_and_activity_routes(workspace):
    store, courses, plan, activities = workspace
    payload = {
        "title": "Independent deadline",
        "kind": "assignment",
        "due_at": "2026-11-01T12:00:00Z",
    }
    save = FakeContext(FakeRequest("PUT", "/v1/courses/poo/dates/manual-test", body_json=payload))
    result = function.main(save)
    assert result["status"] == 200
    assert result["body"]["date"]["source"] == "manual"
    listing = function.main(FakeContext(FakeRequest("GET", "/v1/courses/poo/dates")))
    assert listing["body"]["dates"][0]["title"] == payload["title"]
    assert (
        function.main(FakeContext(FakeRequest("GET", "/v1/courses/poo/plan")))["body"]["plan"]
        is not None
    )
    listing = function.main(
        FakeContext(
            FakeRequest("GET", "/v1/courses/poo/activities", headers={"X-Academic-Contract": "2"})
        )
    )
    assert listing["body"]["activities"][0]["description"] == "Task"
    assert (
        function.main(FakeContext(FakeRequest("GET", "/v1/courses/poo/activities/20")))["body"][
            "description"
        ]
        == "Task"
    )
    deleted = function.main(FakeContext(FakeRequest("DELETE", "/v1/courses/poo/dates/manual-test")))
    assert deleted["body"] == {"deleted": True}
    assert not store.documents
    events = [json.loads(row) for row in save.logs]
    assert any(
        row["event"] == "course_workspace_succeeded"
        and row["course_id"] == "poo"
        and row["stage"] == "dates_put"
        and "request_id" in row
        for row in events
    )

    def absent(identifier):
        raise TeachingPlanNotFound()

    plan.load = absent
    assert function.main(FakeContext(FakeRequest("GET", "/v1/courses/poo/plan")))["body"] == {
        "plan": None
    }


@pytest.mark.parametrize(
    "method,path", [("GET", "dates/20"), ("PUT", "dates"), ("DELETE", "plan"), ("GET", "plan/20")]
)
def test_workspace_rejects_unsupported_actions_without_a_write(workspace, method, path):
    store, *_ = workspace
    assert (
        function.main(FakeContext(FakeRequest(method, "/v1/courses/poo/" + path)))["status"] == 404
    )
    assert store.documents == {}


@pytest.mark.parametrize(
    "error,status",
    [
        (CourseMoodleNotLinked(), 409),
        (UFMGReauthenticationRequired(), 401),
        (InvalidMoodleResponse("activity_page_endpoint"), 502),
        (MoodleUnavailable(), 503),
        (UFMGSessionStoreUnavailable(), 503),
        (MoodleTokenStoreUnavailable(), 503),
        (InvalidAcademicDate(), 400),
        (InvalidTeachingPlan(), 500),
        (FirestoreNotFound(), 404),
        (FirestoreAccessDenied(), 403),
        (FirestoreUnavailable(), 503),
        (FirestoreRequestRejected(), 503),
    ],
)
def test_workspace_failures_identify_course_stage_and_reason(workspace, error, status):
    _, courses, *_ = workspace

    def fail(identifier):
        raise error

    courses.get_course = fail
    context = FakeContext(FakeRequest("GET", "/v1/courses/poo/plan"))
    response = function.main(context)
    assert response["status"] == status
    rows = [json.loads(row) for row in context.logs + context.errors]
    failure = next(row for row in rows if row["event"] == "course_workspace_failed")
    assert failure["course_id"] == "poo"
    assert failure["stage"] == "course_lookup"
    assert failure["duration_ms"] >= 0


def test_workspace_authentication_rejection_does_not_read_course(monkeypatch):
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, {"status": 401}))
    assert function.main(FakeContext(FakeRequest("GET", "/v1/courses/poo/plan"))) == {"status": 401}


def test_legacy_counter_contract_is_preserved_while_new_client_gets_diagnostics():
    summary = {
        "total": 1,
        "matched": 0,
        "unmatched": 1,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "unmatched_events": [{"title": "Unmatched"}],
    }
    for body in [summary, {"dates": summary}, {"moodle": {"dates": summary}}]:
        old = FakeContext(FakeRequest("GET", "/"))
        new = FakeContext(FakeRequest("GET", "/", headers={"X-Academic-Contract": "2"}))
        assert "unmatched_events" not in str(function._respond(old, body)["body"])
        assert "unmatched_events" in str(function._respond(new, body)["body"])
