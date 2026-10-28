from copy import deepcopy

import pytest

from course_sync_policy import CourseSyncPolicy, SyncDeferred
from firestore_rest import FirestoreNotFound


class Store:
    def __init__(self):
        self.docs = {}
        self.writes = 0

    def get_user_document(self, *path):
        if path not in self.docs:
            raise FirestoreNotFound()
        return deepcopy(self.docs[path])

    def patch_user_document(self, *path, fields):
        self.docs[path] = {"fields": deepcopy(fields)}
        self.writes += 1
        return self.docs[path]


def test_repeat_sync_reuses_recent_activities_but_does_not_freeze_them_forever():
    store = Store()
    policy = CourseSyncPolicy(store)
    calls = []

    def fetch():
        calls.append("moodle")
        return {"activity_count": 12}

    assert policy.run("course1", "activities", "2026-2", now=1000, fetch=fetch)[1] is False
    assert policy.run("course1", "activities", "2026-2", now=1001, fetch=fetch)[1] is True
    assert len(calls) == 1
    assert policy.run("course1", "activities", "2026-2", now=1000 + 21600, fetch=fetch)[1] is False
    assert len(calls) == 2


def test_complete_plan_stops_automatic_queries_but_force_and_new_source_refresh():
    policy = CourseSyncPolicy(Store())
    calls = []

    def fetch():
        calls.append(1)
        return {
            "criteria_total": 1,
            "schedule_total": 30,
            "assessment_total": 3,
            "undated_assessment_total": 0,
        }

    policy.run("course1", "plan", "2026-2:123", now=1000, fetch=fetch)
    assert policy.run("course1", "plan", "2026-2:123", now=9999999, fetch=fetch)[1]
    policy.run("course1", "plan", "2026-2:123", now=9999999, fetch=fetch, force=True)
    policy.run("course1", "plan", "2027-1:456", now=10000000, fetch=fetch)
    assert len(calls) == 3


def test_partial_plan_retries_then_stops_after_thirty_days_without_deleting_copy():
    policy = CourseSyncPolicy(Store())
    calls = []

    def fetch():
        calls.append(1)
        return {"plan": "not_published"}

    policy.run("course1", "plan", "2026-2:123", now=1000, fetch=fetch)
    assert policy.run("course1", "plan", "2026-2:123", now=1001, fetch=fetch)[1]
    assert policy.run("course1", "plan", "2026-2:123", now=1000 + 86400, fetch=fetch)[1] is False
    assert policy.run("course1", "plan", "2026-2:123", now=1000 + 30 * 86400, fetch=fetch)[1]
    assert len(calls) == 2


def test_failure_backoff_is_per_course_preserves_previous_and_never_implies_completeness():
    policy = CourseSyncPolicy(Store())
    events = []
    policy.telemetry = lambda event, fields: events.append((event, fields))

    def fail():
        raise RuntimeError("private")

    with pytest.raises(RuntimeError):
        policy.run("course1", "activities", "2026-2", now=1000, fetch=fail)
    with pytest.raises(SyncDeferred):
        policy.run("course1", "activities", "2026-2", now=1001, fetch=fail)
    assert (
        policy.run(
            "course2", "activities", "2026-2", now=1001, fetch=lambda: {"activity_count": 2}
        )[0]["activity_count"]
        == 2
    )
    with pytest.raises(RuntimeError):
        policy.run("course1", "activities", "2026-2", now=1900, fetch=fail)
    assert events[-1][1]["next_due_at"] == 3700
    assert "private" not in str(events)


def test_manual_review_stops_plan_search_without_guessing_assessment_counts():
    policy = CourseSyncPolicy(Store())
    policy.confirm_plan("course1", now=1000)
    with pytest.raises(SyncDeferred):
        policy.run("course1", "plan", "2026-2:123", now=1001, fetch=lambda: None)


def test_policy_field_completeness_manual_resume_and_adapter_are_explicit():
    from types import SimpleNamespace

    from course_sync_policy import AdaptiveTeachingPlanImporter

    policy = CourseSyncPolicy(Store())
    with pytest.raises(ValueError):
        policy.state("course1", "unknown")
    policy.confirm_plan("course1", now=1000, term="2026-2")
    adapter = AdaptiveTeachingPlanImporter(None, policy)
    assert adapter.import_plan(
        "user", course_id="course1", term="2026-2", source_id=123, now=1001
    ) == {"plan": "deferred"}
    policy.confirm_plan("course1", now=1002, term="2026-2", paused=False)
    source = SimpleNamespace(
        import_plan=lambda *a, **k: {
            "criteria_total": 1,
            "schedule_total": 1,
            "assessment_total": 2,
            "undated_assessment_total": 1,
        }
    )
    adapter = AdaptiveTeachingPlanImporter(source, policy)
    assert (
        adapter.import_plan("user", course_id="course1", term="2026-2", source_id=123, now=1003)[
            "undated_assessment_total"
        ]
        == 1
    )
    assert policy.state("course1", "plan")["complete_fields"] == ["criteria", "schedule"]
    adapter.force = True
    assert (
        adapter.import_plan("user", course_id="course1", term="2026-2", source_id=123, now=1004)[
            "criteria_total"
        ]
        == 1
    )


def test_manual_policy_http_route_is_owned_validated_and_persistent(monkeypatch):
    from types import SimpleNamespace

    from test_main import FakeContext, FakeRequest

    import main as function
    from firestore_rest import FirestoreUnavailable

    store = Store()
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    monkeypatch.setattr(function, "_firestore", lambda *_: store)
    monkeypatch.setattr(
        function,
        "_course_repository",
        lambda *_: SimpleNamespace(get_course=lambda _: {"term": "2026-2"}),
    )
    context = FakeContext(
        FakeRequest("PUT", "/v1/courses/course1/plan-sync", body_json={"paused": True})
    )
    assert function.main(context)["body"] == {"paused": True}
    context.req.method = "GET"
    assert function.main(context)["body"] == {"paused": True}
    context.req.method = "PUT"
    context.req.body_json = {"paused": "yes"}
    assert function.main(context)["status"] == 400
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, {"status": 401}))
    assert function.main(context)["status"] == 401
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    monkeypatch.setattr(
        function, "_firestore", lambda *_: (_ for _ in ()).throw(FirestoreUnavailable())
    )
    assert function.main(context)["status"] == 503


def test_source_and_metadata_failures_both_remain_visible():
    from firestore_rest import FirestoreUnavailable

    store = Store()
    events = []
    policy = CourseSyncPolicy(store, telemetry=lambda e, f: events.append((e, f)))
    store.patch_user_document = lambda *a, **k: (_ for _ in ()).throw(FirestoreUnavailable())
    with pytest.raises(FirestoreUnavailable):
        policy.run(
            "course1",
            "activities",
            "2026-2",
            now=1000,
            fetch=lambda: (_ for _ in ()).throw(RuntimeError("private")),
        )
    assert [e for e, f in events][-2:] == [
        "course_sync_attempt_failed",
        "course_sync_policy_persistence_failed",
    ]
    assert events[-2][1]["reason"] == "RuntimeError"
    assert events[-1][1]["reason"] == "FirestoreUnavailable"


def test_force_does_not_clear_manual_pause_and_a_new_term_does_not_inherit_it():
    policy = CourseSyncPolicy(Store())
    policy.confirm_plan("course1", now=1000, term="2026-2")
    policy.run("course1", "plan", "2026-2:123", now=1001, fetch=lambda: {}, force=True)
    assert policy.manual_paused("course1", "2026-2") is True
    assert policy.run("course1", "plan", "2026-2:123", now=1002, fetch=lambda: {"changed": True})[1]
    assert policy.run("course1", "plan", "2027-1:456", now=1003, fetch=lambda: {"new_term": True})[
        0
    ]["new_term"]


def test_existing_course_gets_one_initial_attempt_then_uses_its_creation_deadline():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from course_sync_policy import AdaptiveTeachingPlanImporter

    policy = CourseSyncPolicy(Store())
    now = 40 * 86400
    calls = []

    def fetch(*a, **k):
        calls.append(1)
        return {"plan": "not_published"}

    adapter = AdaptiveTeachingPlanImporter(
        SimpleNamespace(import_plan=fetch),
        policy,
        created_at=lambda _: datetime.fromtimestamp(1000, UTC).isoformat(),
    )
    assert (
        adapter.import_plan("user", course_id="course1", term="2026-2", source_id=123, now=now)[
            "plan"
        ]
        == "not_published"
    )
    assert (
        adapter.import_plan("user", course_id="course1", term="2026-2", source_id=123, now=now + 1)[
            "plan"
        ]
        == "not_published"
    )
    assert len(calls) == 1
    assert policy.state("course1", "plan")["first_seen_at"] == 1000


@pytest.mark.parametrize("contract", ["2", "3"])
def test_new_reuse_metrics_do_not_break_the_installed_apk_contract(contract):
    from test_main import FakeContext, FakeRequest

    import main as function

    activities = {"updated": 0, "failed": 0, "failed_courses": [], "reused": 9}
    result = {"moodle": {"activities": activities}}
    context = FakeContext(
        FakeRequest("GET", "/v1/ufmg/sync/job", headers={"x-academic-contract": contract})
    )
    body = function._respond(context, {"result": result})["body"]
    assert ("reused" in body["result"]["moodle"]["activities"]) == (contract == "3")
    assert result["moodle"]["activities"]["reused"] == 9


def test_manual_pause_after_term_edit_does_not_reuse_old_term_data():
    policy = CourseSyncPolicy(Store())
    policy.run("course1", "plan", "2026-2:123", now=1000, fetch=lambda: {"old": True})
    policy.confirm_plan("course1", now=2000, term="2027-1")
    assert policy.state("course1", "planPreference")["source_key"] == "2027-1"
    with pytest.raises(SyncDeferred):
        policy.run("course1", "plan", "2027-1:456", now=2001, fetch=lambda: {})


def test_manual_pause_during_fetch_survives_automatic_completion():
    policy = CourseSyncPolicy(Store())

    def fetch():
        policy.confirm_plan("course1", now=1001, term="2026-2")
        return {"criteria_total": 1}

    policy.run("course1", "plan", "2026-2:123", now=1000, fetch=fetch)
    assert policy.manual_paused("course1", "2026-2")
    assert policy.run(
        "course1",
        "plan",
        "2026-2:123",
        now=1002,
        fetch=lambda: (_ for _ in ()).throw(AssertionError("paused source fetched")),
    )[1]


def test_deferred_failure_without_a_previous_plan_remains_visible_to_the_user():
    from course_sync_policy import AdaptiveTeachingPlanImporter

    policy = CourseSyncPolicy(Store())
    with pytest.raises(RuntimeError):
        policy.run(
            "course1",
            "plan",
            "2026-2:123",
            now=1000,
            fetch=lambda: (_ for _ in ()).throw(RuntimeError()),
        )
    adapter = AdaptiveTeachingPlanImporter(None, policy)
    assert adapter.import_plan(
        "user", course_id="course1", term="2026-2", source_id=123, now=1001
    ) == {"plan": "unavailable"}


def test_explicit_force_also_applies_to_synchronous_compatibility_requests(monkeypatch):
    from types import SimpleNamespace

    from test_main import FakeContext, FakeRequest

    import main as function

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    options = []

    def factory(*a, **kw):
        options.append(kw)
        return SimpleNamespace(
            sync=lambda *a, **kw: {
                "exceptions": [],
                "teaching_plans": {
                    "available": 0,
                    "imported": 0,
                    "applied": 0,
                    "unchanged": 0,
                    "review_required": 0,
                },
            }
        )

    monkeypatch.setattr(function, "_unified_academic_sync_service", factory)
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all", body_json={"force": True}))
    assert function.main(context)["status"] == 200
    assert options == [{"force": True}]
