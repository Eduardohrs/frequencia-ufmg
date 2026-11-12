"""Tests for the Appwrite registration-draft persistence used by the function."""

import json

import pytest
from appwrite.exception import AppwriteException
from test_pendency_repository import FakeDatabases, parse_queries  # noqa: F401  (shared fake)

import draft_repository as module
from appwrite_storage import StorageNotProvisioned, StorageUnavailable
from course_service import InvalidCourse
from draft_repository import DraftRepository


@pytest.fixture()
def databases(monkeypatch: pytest.MonkeyPatch) -> FakeDatabases:
    fake = FakeDatabases(client=object())
    monkeypatch.setattr(module, "Databases", lambda client: fake)
    return fake


def _save(repo: DraftRepository, user_id: str = "user-1", **overrides: object) -> str:
    fields = {
        "user_id": user_id,
        "course_id": "course-1",
        "course_code": "DCC205",
        "session_id": "session-1",
        "form_data": {"code": "DCC205", "name": "Estruturas"},
    }
    fields.update(overrides)
    return repo.save_draft(**fields)  # type: ignore[arg-type]


def test_save_and_get_draft_round_trips_owner_and_form_data(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    form_data = {"code": "DCC205", "name": "Estruturas de Dados"}

    draft_id = repo.save_draft(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        session_id="session-1",
        form_data=form_data,
        last_error="rate_limited",
        attempt_count=2,
    )

    assert draft_id
    created = databases.created[0]["data"]
    assert created["user_id"] == "user-1"
    assert json.loads(created["form_data"]) == form_data
    assert created["last_error"] == "rate_limited"
    assert created["attempt_count"] == 2
    assert len(databases.created[0]["permissions"]) == 3

    fetched = repo.get_draft(draft_id, "user-1")
    assert fetched is not None
    assert fetched["form_data"] == form_data
    assert repo.get_draft(draft_id, "user-2") is None
    assert repo.get_draft("missing", "user-1") is None


def test_save_draft_requires_user_id_and_validates_course(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    with pytest.raises(ValueError):
        _save(repo, user_id="")
    with pytest.raises(InvalidCourse):
        _save(repo, course_id="bad/id")
    databases.fail_create = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        _save(repo)
    databases.fail_create = AppwriteException("missing", code=404, type="database_not_found")
    with pytest.raises(StorageNotProvisioned):
        _save(repo)


def test_get_draft_distinguishes_not_found_from_failures(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo)
    databases.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.get_draft(draft_id, "user-1")
    databases.fail_get = AppwriteException("down", code=503)
    with pytest.raises(StorageUnavailable):
        repo.get_draft(draft_id, "user-1")


def test_update_draft_only_for_owner(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo, user_id="user-1")

    assert repo.update_draft(draft_id, "user-2", last_error="x") is False
    assert databases.documents[draft_id]["last_error"] is None

    assert repo.update_draft(draft_id, "user-1", last_error="rate_limited", attempt_count=3) is True
    document = databases.documents[draft_id]
    assert document["last_error"] == "rate_limited"
    assert document["attempt_count"] == 3
    assert json.loads(document["form_data"]) == {"code": "DCC205", "name": "Estruturas"}

    assert repo.update_draft(draft_id, "user-1", form_data={"code": "DCC206"}) is True
    assert json.loads(databases.documents[draft_id]["form_data"]) == {"code": "DCC206"}
    assert repo.update_draft("missing", "user-1", last_error="x") is False


def test_update_draft_maps_race_not_found_and_failures(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo)
    databases.fail_update = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.update_draft(draft_id, "user-1", last_error="x") is False
    databases.fail_update = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.update_draft(draft_id, "user-1", last_error="x")


def test_list_drafts_filters_by_user_course_session_and_decodes(
    databases: FakeDatabases,
) -> None:
    repo = DraftRepository(client=object())
    _save(repo, user_id="user-1", course_id="course-1", session_id="session-1")
    _save(repo, user_id="user-1", course_id="course-2", session_id="session-2")
    _save(repo, user_id="user-2", course_id="course-1", session_id="session-1")

    drafts = repo.list_drafts(user_id="user-1")
    assert len(drafts) == 2
    assert all(draft["form_data"]["code"] == "DCC205" for draft in drafts)
    assert len(repo.list_drafts(user_id="user-2")) == 1
    assert len(repo.list_drafts(user_id="user-1", course_id="course-2")) == 1
    filtered = repo.list_drafts(user_id="user-1", course_id="course-1", session_id="session-1")
    assert len(filtered) == 1
    for queries in databases.seen_queries:
        parsed = [json.loads(raw) for raw in queries]
        assert any(
            item["method"] == "equal" and item["attribute"] == "user_id" for item in parsed
        )


def test_list_drafts_requires_user_id_and_propagates_failures(
    databases: FakeDatabases,
) -> None:
    repo = DraftRepository(client=object())
    with pytest.raises(ValueError):
        repo.list_drafts(user_id="")
    _save(repo)
    databases.fail_list = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.list_drafts(user_id="user-1")
    databases.fail_list = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.list_drafts(user_id="user-1")


def test_delete_draft_only_for_owner(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo, user_id="user-1")

    assert repo.delete_draft(draft_id, "user-2") is False
    assert draft_id in databases.documents
    assert repo.delete_draft(draft_id, "user-1") is True
    assert repo.delete_draft(draft_id, "user-1") is False
    databases.fail_delete = AppwriteException("down", code=500)
    other = _save(repo, user_id="user-1")
    with pytest.raises(StorageUnavailable):
        repo.delete_draft(other, "user-1")


def test_get_draft_without_form_data_and_list_without_form_data(
    databases: FakeDatabases,
) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo, form_data={"a": 1})
    databases.documents[draft_id].pop("form_data")
    assert repo.get_draft(draft_id, "user-1")["$id"] == draft_id
    drafts = repo.list_drafts(user_id="user-1")
    assert drafts[0].get("form_data") is None


def test_get_draft_returns_empty_document_when_present(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    databases.documents["empty"] = {"user_id": "user-1"}
    assert repo.get_draft("empty", "user-1") == {"user_id": "user-1"}


def test_delete_draft_maps_race_not_found(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = _save(repo)
    databases.fail_delete = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.delete_draft(draft_id, "user-1") is False
