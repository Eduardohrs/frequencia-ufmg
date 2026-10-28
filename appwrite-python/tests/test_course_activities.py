from types import SimpleNamespace

import pytest

from course_activities import CourseActivityService, CourseMoodleNotLinked
from moodle_structured_dates import InvalidMoodleResponse
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
        capabilities,
        telemetry=lambda event, fields: logs.append((event, fields)),
    )
    return service, catalog, sessions, client, tokens, capabilities, logs, valid


def test_lists_and_reads_owned_activity_without_reading_any_student_file(activities):
    service, _, _, client, *_ = activities
    assert service.list_activities("user", "poo", now=123)["activities"][0]["source_id"] == "20"
    assert service.detail("user", "poo", "20", now=123)["description"] == "Read this"
    with pytest.raises(InvalidMoodleResponse) as rejected:
        service.detail("user", "poo", "999", now=123)
    assert rejected.value.reason == "course_activity_not_found"
    client.fetch_activity = lambda *args, **kwargs: {"attachments": "invalid"}
    with pytest.raises(InvalidMoodleResponse) as rejected:
        service.detail("user", "poo", "20", now=123)
    assert rejected.value.reason == "activity_attachment_shape"


def test_attachment_credentials_are_delivered_only_to_client_and_not_telemetry(activities):
    service, _, _, client, tokens, capabilities, logs, valid = activities
    client.fetch_activity = lambda *args, **kwargs: {
        "description": "Read this",
        "submission_state": "not_submitted",
        "attachments": [
            {
                "name": "instructions.pdf",
                "url": "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_assign/introattachment/0/instructions.pdf",
            }
        ],
    }
    result = service.detail("user", "poo", "20", now=123)
    assert "/tokenpluginfile.php/" in result["files"][0]["url"]
    assert valid.private_token not in str(logs)
    tokens.load = lambda *args, **kwargs: None
    assert service.detail("user", "poo", "20", now=123)["files"] == []
    assert logs[-2][0] == "course_activity_download_unavailable"
    loads = iter([None, valid])
    tokens.load = lambda *args, **kwargs: next(loads)
    assert len(service.detail("user", "poo", "20", now=123)["files"]) == 1


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
