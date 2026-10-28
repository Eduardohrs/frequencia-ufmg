import copy
import json
from types import SimpleNamespace

import pytest
from test_academic_date_repository import _Firestore
from test_course_activities import activities as activity_fixture
from test_main import FakeContext, FakeRequest

import main as function
from activity_snapshot_repository import (
    ActivitySnapshotMissing,
    ActivitySnapshotRepository,
    InvalidActivitySnapshot,
    _encode,
)
from moodle_structured_dates import MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable


@pytest.fixture
def activities():
    return activity_fixture.__wrapped__()


class Store(_Firestore):
    def get_user_document(self, *path):
        return {"fields": self.documents[tuple(path)]}


def snapshot():
    return {
        "course_id": "poo",
        "term": "2026-2",
        "synced_at": "2026-10-28T12:00:00Z",
        "activities": [
            {
                "source_id": "20",
                "description": "Saved task",
                "attachments": [],
                "files": [],
                "term": "2026-2",
            }
        ],
    }


def test_snapshot_atomic_replacement_and_failure_preserve_the_last_version():
    store = Store()
    repo = ActivitySnapshotRepository(store)
    with pytest.raises(ActivitySnapshotMissing):
        repo.load("poo")
    repo.save("poo", snapshot())
    before = copy.deepcopy(store.documents)
    assert repo.load("poo") == snapshot()
    for invalid in [
        None,
        {},
        {**snapshot(), "activities": "bad"},
        {**snapshot(), "activities": [{}]},
        {
            **snapshot(),
            "activities": [{**snapshot()["activities"][0], "files": [{"url": "secret"}]}],
        },
        {
            **snapshot(),
            "activities": [{**snapshot()["activities"][0], "description": "x" * 750001}],
        },
        {**snapshot(), "activities": [snapshot()["activities"][0]] * 501},
    ]:
        with pytest.raises(InvalidActivitySnapshot):
            repo.save("poo", invalid)
        assert store.documents == before
    with pytest.raises(InvalidActivitySnapshot):
        repo.save("other", snapshot())
    fields = next(iter(store.documents.values()))
    fields["contentHash"] = {"stringValue": "bad"}
    with pytest.raises(InvalidActivitySnapshot):
        repo.load("poo")
    fields["snapshotJson"] = {"stringValue": "invalid json"}
    with pytest.raises(InvalidActivitySnapshot):
        repo.load("poo")
    with pytest.raises(InvalidActivitySnapshot):
        _encode(
            {**snapshot(), "activities": [{**snapshot()["activities"][0], "unexpected": object()}]}
        )


def test_sync_captures_all_content_and_keeps_failed_course_while_other_courses_update(activities):
    service, _, sessions, client, tokens, _, logs, _ = activities
    service._courses.list_courses = lambda: [
        {"id": "poo", "code": "ELE631", "term": "2026-2"},
        {"id": "other", "code": "ELE999", "term": "2026-2"},
    ]
    service._courses.get_course = lambda identifier: {
        "id": identifier,
        "code": "ELE631",
        "term": "2026-2",
    }
    store = Store()
    repo = ActivitySnapshotRepository(store)
    repo.save("poo", snapshot())

    def fetch(*args, **kwargs):
        raise MoodleUnavailable("upstream unavailable")

    client.fetch_activity = fetch
    result = service.sync_snapshots("owner", now=1793188800, snapshots=repo)
    assert result["failed"] == 2 and repo.load("poo") == snapshot()
    client.fetch_activity = lambda *a, **k: {
        "description": "New text",
        "attachments": [],
        "submission_state": "submitted",
    }
    result = service.sync_snapshots("owner", now=1793188800, snapshots=repo)
    assert result["updated"] == 2 and result["failed"] == 0
    saved = repo.load("poo")
    assert saved["activities"][0]["description"] == "New text"
    assert saved["activities"][0]["files"] == []
    assert "private_token" not in json.dumps(saved)
    assert any(
        event == "academic_sync_stage_completed" and fields["stage"] == "activity_snapshot_persist"
        for event, fields in logs
    )
    previous = copy.deepcopy(store.documents)
    # Only one course fails; the successful one still receives a new snapshot.
    original = service._catalog.list_catalog
    service._catalog.list_catalog = lambda courses: (
        [] if courses[0]["id"] == "poo" else original(courses)
    )
    result = service.sync_snapshots("owner", now=1793192400, snapshots=repo)
    assert result["updated"] == 1 and result["failed"] == 1
    assert (
        store.documents[("courses", "poo", "activitySnapshots", "current")]
        == previous[("courses", "poo", "activitySnapshots", "current")]
    )


def test_authorizing_saved_content_never_loads_a_session_or_calls_moodle(activities):
    service, _, sessions, client, tokens, _, logs, _ = activities

    def forbidden(*args, **kwargs):
        raise AssertionError("Moodle access during saved read")

    sessions.load = forbidden
    client.fetch_activity = forbidden
    client.list_activities = forbidden
    detail = {
        **snapshot()["activities"][0],
        "attachments": [
            {
                "name": "guide.pdf",
                "url": "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_assign/introattachment/0/guide.pdf",
            }
        ],
    }
    assert service.authorize_saved("owner", "poo", detail, now=1)["files"][0]["name"] == "guide.pdf"
    tokens.load = lambda *a, **k: None
    assert service.authorize_saved("owner", "poo", detail, now=1)["files"] == []

    def unavailable(*a, **k):
        raise MoodleTokenStoreUnavailable()

    tokens.load = unavailable
    assert service.authorize_saved("owner", "poo", detail, now=1)["description"] == "Saved task"
    assert any(event == "activity_snapshot_download_unavailable" for event, _ in logs)


def test_saved_api_works_with_expired_session_and_reports_missing_or_corrupt_snapshot(monkeypatch):
    store = Store()
    repo = ActivitySnapshotRepository(store)
    repo.save("poo", snapshot())
    monkeypatch.setattr(function, "_authentication", lambda *_: ("owner", None))
    monkeypatch.setattr(
        function,
        "_course_repository",
        lambda *_: SimpleNamespace(get_course=lambda _: {"id": "poo", "code": "ELE631"}),
    )
    monkeypatch.setattr(function, "_firestore", lambda *_: store)

    def forbidden(*a, **k):
        raise MoodleUnavailable("Moodle is down")

    monkeypatch.setattr(function, "_course_activity_service", forbidden)

    def get(suffix=""):
        return function.main(
            FakeContext(
                FakeRequest(
                    "GET",
                    "/v1/courses/poo/activities" + suffix,
                    headers={"X-Academic-Contract": "2"},
                )
            )
        )

    assert get()["body"]["activities"][0]["description"] == "Saved task"
    context = FakeContext(
        FakeRequest("GET", "/v1/courses/poo/activities", headers={"X-Academic-Contract": "2"})
    )
    function.main(context)
    assert any(
        json.loads(row).get("snapshot_synced_at") == snapshot()["synced_at"] for row in context.logs
    )
    assert get("/20")["body"]["description"] == "Saved task"
    assert get("/99")["status"] == 404
    store.documents.clear()
    assert get()["status"] == 409
    store.documents[("courses", "poo", "activitySnapshots", "current")] = {}
    assert get()["status"] == 500


def test_snapshot_failure_retains_parser_reason_and_keeps_previous_copy(activities):
    from moodle_structured_dates import InvalidMoodleResponse

    service, _, _, client, _, _, logs, _ = activities
    service._courses.list_courses = lambda: [{"id": "poo", "code": "ELE631", "term": "2026-2"}]
    repo = ActivitySnapshotRepository(Store())
    repo.save("poo", snapshot())

    def fail(*args, **kwargs):
        raise InvalidMoodleResponse("activity_page_shape")

    client.fetch_activity = fail
    result = service.sync_snapshots("owner", now=1793188800, snapshots=repo)
    assert result["failed_courses"][0]["reason"] == "activity_page_shape"
    assert repo.load("poo") == snapshot()
    failures = [fields for event, fields in logs if event == "academic_sync_stage_failed"]
    assert failures[0]["reason"] == "activity_page_shape"
    assert failures[0]["kind"] == "assign"
    assert failures[0]["source_id"] == "20"
    assert failures[0]["title"]
