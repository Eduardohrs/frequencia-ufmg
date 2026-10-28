from types import SimpleNamespace

import pytest

from course_activities import CourseActivityService, CourseMoodleNotLinked
from ufmg_session_store import UFMGReauthenticationRequired


@pytest.fixture
def activities():
    entry = {
        "source_id": "20",
        "title": "Task",
        "kind": "assign",
        "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=20",
        "relevance": "other",
    }
    course = {"id": "poo", "code": "ELE631", "term": "2026-2"}
    catalog = SimpleNamespace(list_catalog=lambda _: [{"status": "found", "moodle_course_id": "1"}])
    sessions = SimpleNamespace(
        load=lambda *args, **kwargs: SimpleNamespace(token="synthetic-session")
    )
    client = SimpleNamespace(
        list_activities=lambda *args, **kwargs: [entry],
        fetch_activity=lambda *args, **kwargs: {
            "description": "Read this",
            "submission_state": "not_submitted",
            "attachments": [],
        },
    )
    valid = SimpleNamespace(term="2026-2", private_token="p" * 32)
    tokens = SimpleNamespace(load=lambda *args, **kwargs: valid)
    capabilities = SimpleNamespace(probe=lambda *args, **kwargs: None)
    logs = []
    service = CourseActivityService(
        SimpleNamespace(get_course=lambda _: course),
        catalog,
        sessions,
        client,
        tokens,
        telemetry=lambda event, fields: logs.append((event, fields)),
    )
    return service, catalog, sessions, client, tokens, capabilities, logs, valid


def test_sync_index_identifies_owned_activities(activities):
    service, *_ = activities
    assert service.list_activities("user", "poo", now=123)["activities"][0]["source_id"] == "20"


def test_attachment_credentials_are_delivered_only_for_download_not_persisted_content(activities):
    service, _, _, _, tokens, _, logs, valid = activities
    saved = {
        "source_id": "20",
        "description": "Read this",
        "term": "2026-2",
        "attachments": [
            {
                "name": "instructions.pdf",
                "url": "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_assign/introattachment/0/instructions.pdf",
            }
        ],
        "files": [],
    }
    result = service.authorize_saved("user", "poo", saved, now=123)
    assert "/tokenpluginfile.php/" in result["files"][0]["url"]
    assert valid.private_token not in str(logs)
    assert saved["files"] == []
    tokens.load = lambda *a, **k: None
    assert service.authorize_saved("user", "poo", saved, now=123)["files"] == []


def test_unlinked_ambiguous_or_expired_sources_are_explicit(activities):
    service, catalog, sessions, *_ = activities
    for value in [
        [],
        [{"status": "ambiguous", "moodle_course_id": "1"}],
        [{"status": "empty", "moodle_course_id": None}],
    ]:
        catalog.list_catalog = lambda _, value=value: value
        with pytest.raises(CourseMoodleNotLinked):
            service.list_activities("user", "poo", now=123)
    catalog.list_catalog = lambda _: [{"status": "empty", "moodle_course_id": "1"}]
    sessions.load = lambda *args, **kwargs: None
    with pytest.raises(UFMGReauthenticationRequired):
        service.list_activities("user", "poo", now=123)


def test_adaptive_capture_reuses_complete_copy_and_can_force_or_heal_missing_copy(activities):
    from test_course_sync_policy import Store

    from activity_snapshot_repository import ActivitySnapshotMissing
    from course_sync_policy import CourseSyncPolicy

    service, _, _, client, *_ = activities
    course = {"id": "poo", "code": "ELE631", "term": "2026-2"}
    service._courses.list_courses = lambda: [course]
    service._policy = CourseSyncPolicy(Store())
    counts = {"index": 0, "detail": 0}
    saved = {}
    old_index = client.list_activities
    old_detail = client.fetch_activity

    def index(*a, **k):
        counts["index"] += 1
        return old_index(*a, **k)

    def detail(*a, **k):
        counts["detail"] += 1
        return old_detail(*a, **k)

    client.list_activities = index
    client.fetch_activity = detail

    class Snapshots:
        def load(self, key):
            if key not in saved:
                raise ActivitySnapshotMissing()
            return saved[key]

        def save(self, key, value):
            saved[key] = value

    snapshots = Snapshots()
    assert service.sync_snapshots("user", now=1000, snapshots=snapshots)["updated"] == 1
    before = dict(counts)
    assert service.sync_snapshots("user", now=1001, snapshots=snapshots)["reused"] == 1
    assert counts == before
    service._force = True
    assert service.sync_snapshots("user", now=1002, snapshots=snapshots)["updated"] == 1
    service._force = False
    saved.clear()
    assert service.sync_snapshots("user", now=1003, snapshots=snapshots)["updated"] == 1
    saved["poo"]["term"] = "2025-2"
    assert service.sync_snapshots("user", now=1004, snapshots=snapshots)["updated"] == 1
