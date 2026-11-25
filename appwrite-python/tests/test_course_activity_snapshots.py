import copy
import json
import time
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
    _estimate_update_bytes,
)
from moodle_structured_dates import MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable


@pytest.fixture
def activities():
    return activity_fixture.__wrapped__()


class Store(_Firestore):
    def get_user_document(self, *path):
        return {"fields": self.documents[tuple(path)]}


class BatchStore:
    def __init__(self) -> None:
        self.commits: list[list[tuple[tuple[str, ...], dict[str, object]]]] = []

    def commit_user_documents(self, *, updates, deletes) -> None:
        assert deletes == []
        self.commits.append(list(updates))


class LegacyStore(Store):
    """Exercise the compatibility path used by older Firestore fakes/clients."""

    commit_user_documents = None


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


def test_snapshot_batch_uses_one_commit_for_small_course_set():
    store = BatchStore()
    repo = ActivitySnapshotRepository(store)
    second = {**snapshot(), "course_id": "mat"}

    repo.save_batch([("poo", snapshot()), ("mat", second)])

    assert len(store.commits) == 1
    assert [path for path, _ in store.commits[0]] == [
        ("courses", "poo", "activitySnapshots", "current"),
        ("courses", "mat", "activitySnapshots", "current"),
    ]


def test_snapshot_batch_falls_back_to_individual_patches_without_commit_api():
    store = LegacyStore()
    repo = ActivitySnapshotRepository(store)
    second = {**snapshot(), "course_id": "mat"}

    repo.save_batch([("poo", snapshot()), ("mat", second)])

    assert [path for path, _ in store.patches] == [
        ("courses", "poo", "activitySnapshots", "current"),
        ("courses", "mat", "activitySnapshots", "current"),
    ]


def test_snapshot_batch_rejects_duplicates_and_supports_empty_input():
    repo = ActivitySnapshotRepository(BatchStore())
    repo.save_batch([])
    with pytest.raises(InvalidActivitySnapshot, match="duplicate snapshot course"):
        repo.save_batch([("poo", snapshot()), ("poo", snapshot())])


def test_snapshot_batch_splits_when_the_commit_budget_is_reached():
    store = BatchStore()
    repo = ActivitySnapshotRepository(store)
    entry = {
        "source_id": "20",
        "description": "x" * 480_000,
        "attachments": [],
        "files": [],
        "term": "2026-2",
    }
    first = {**snapshot(), "activities": [entry]}
    second = {**first, "course_id": "mat"}

    repo.save_batch([("poo", first), ("mat", second)])

    assert len(store.commits) == 2
    assert _estimate_update_bytes(*store.commits[0][0]) > 400_000


def test_snapshot_batch_splits_at_the_security_rules_parent_limit():
    store = BatchStore()
    repo = ActivitySnapshotRepository(store)
    snapshots = [
        (f"course-{index}", {**snapshot(), "course_id": f"course-{index}"})
        for index in range(21)
    ]

    repo.save_batch(snapshots)

    assert [len(commit) for commit in store.commits] == [20, 1]


def test_capture_persists_immediately_without_a_pending_batch(activities):
    service, _, _, _, _, _, _, _ = activities
    service._courses.list_courses = lambda: [{"id": "poo", "code": "ELE631", "term": "2026-2"}]
    store = Store()
    repo = ActivitySnapshotRepository(store)

    service._capture_snapshot("owner", {"id": "poo", "code": "ELE631", "term": "2026-2"}, 1, repo)

    assert repo.load("poo")["course_id"] == "poo"


def test_snapshot_batch_estimator_rejects_non_serializable_fields():
    with pytest.raises(InvalidActivitySnapshot, match="invalid activity snapshot"):
        _estimate_update_bytes(("courses", "poo"), {"bad": object()})


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

    first = FakeContext(
        FakeRequest("GET", "/v1/courses/poo/activities", headers={"X-Academic-Contract": "2"})
    )
    assert function.main(first)["body"]["activities"][0]["description"] == "Saved task"
    assert any(
        json.loads(row).get("snapshot_synced_at") == snapshot()["synced_at"] for row in first.logs
    )
    context = FakeContext(
        FakeRequest("GET", "/v1/courses/poo/activities", headers={"X-Academic-Contract": "2"})
    )
    function.main(context)
    # Ler repetidamente o mesmo relatório não cria novas escritas de log,
    # mas o log por requisição continua emitido.
    assert not any(
        json.loads(row).get("snapshot_synced_at") == snapshot()["synced_at"] for row in context.logs
    )
    assert any(json.loads(row).get("event") == "request_completed" for row in context.logs)
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


def test_snapshot_order_is_deterministic_and_partial_failure_keeps_the_stored_copy(activities):
    from moodle_structured_dates import InvalidMoodleResponse

    service, _, _, client, _, _, logs, _ = activities
    service._courses.list_courses = lambda: [{"id": "poo", "code": "ELE631", "term": "2026-2"}]
    entries = [
        {
            "source_id": str(i),
            "title": f"T{i}",
            "kind": "assign" if i % 2 else "quiz",
            "url": f"https://virtual.ufmg.br/20262/mod/assign/view.php?id={i}",
            "relevance": "other",
        }
        for i in range(1, 7)
    ]
    client.list_activities = lambda *args, **kwargs: entries

    def fetch(token, *, term, source_id, kind):
        # Earlier indexes finish later, so completions arrive out of order.
        time.sleep(0.03 * (len(entries) - source_id))
        if source_id == 2:
            raise InvalidMoodleResponse("activity_page_shape", details={"upstream_status": 503})
        return {"description": f"d{source_id}", "attachments": [], "submission_state": "open"}

    client.fetch_activity = fetch
    store = Store()
    repo = ActivitySnapshotRepository(store)
    repo.save("poo", snapshot())
    before = copy.deepcopy(store.documents)
    result = service.sync_snapshots("owner", now=1793188800, snapshots=repo)
    assert result["failed"] == 1 and result["updated"] == 0
    assert result["failed_courses"][0]["reason"] == "activity_page_shape"
    # The stored snapshot is byte-identical to the previous valid copy.
    assert store.documents == before
    assert repo.load("poo") == snapshot()
    failures = [f for e, f in logs if e == "activity_snapshot_activity_failed"]
    assert len(failures) == 1
    assert failures[0]["source_id"] == "2"
    assert failures[0]["upstream_class"] == "http_503"
    assert failures[0]["upstream_status"] == 503
    assert failures[0]["reason"] == "activity_page_shape"
    summary = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert summary["failed_activities"] == 1 and summary["failed"] == 1

    client.fetch_activity = lambda token, *, term, source_id, kind: {
        "description": f"d{source_id}",
        "attachments": [],
        "submission_state": "open",
    }
    result = service.sync_snapshots("owner", now=1793188801, snapshots=repo)
    assert result["updated"] == 1 and result["failed"] == 0
    saved = repo.load("poo")
    assert [a["source_id"] for a in saved["activities"]] == [str(i) for i in range(1, 7)]
    assert [a["description"] for a in saved["activities"]] == [f"d{i}" for i in range(1, 7)]
    assert all(a["files"] == [] and a["term"] == "2026-2" for a in saved["activities"])
