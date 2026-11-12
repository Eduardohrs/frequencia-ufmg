"""Tests for the Appwrite registration-draft persistence used by the function.

Real Appwrite SDK 27.1.0 services run against a fake HTTP transport (only
``client.call`` is monkeypatched); the shared transport fakes live in
``test_pendency_repository``.
"""

import json

import pytest
from appwrite.client import Client
from appwrite.exception import AppwriteException
from test_pendency_repository import DocumentServer, FakeTransport, make_client

from appwrite_storage import (
    DATABASE_ID,
    DRAFT_COLLECTION_ID,
    StorageNotProvisioned,
    StorageUnavailable,
)
from course_service import InvalidCourse
from draft_repository import DraftRepository


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Client, DocumentServer, FakeTransport]:
    server = DocumentServer(database_id=DATABASE_ID, collection_id=DRAFT_COLLECTION_ID)
    client, transport = make_client(monkeypatch, server)
    return client, server, transport


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


def test_save_and_get_draft_round_trips_owner_and_form_data(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
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
    created = server.created[0]["data"]
    assert created["user_id"] == "user-1"
    assert json.loads(created["form_data"]) == form_data  # stored as a JSON string
    assert created["last_error"] == "rate_limited"
    assert created["attempt_count"] == 2
    assert len(server.created[0]["permissions"]) == 3

    fetched = repo.get_draft(draft_id, "user-1")
    assert fetched is not None
    assert fetched["$id"] == draft_id  # metadata preserved, data merged at top level
    assert fetched["form_data"] == form_data  # decoded back into a dict
    assert "data" not in fetched
    assert repo.get_draft(draft_id, "user-2") is None
    assert repo.get_draft("missing", "user-1") is None


def test_save_draft_requires_user_id_and_validates_course(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    with pytest.raises(ValueError):
        _save(repo, user_id="")
    with pytest.raises(InvalidCourse):
        _save(repo, course_id="bad/id")
    server.fail_create = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        _save(repo)
    server.fail_create = AppwriteException("missing", code=404, type="database_not_found")
    with pytest.raises(StorageNotProvisioned):
        _save(repo)


def test_get_draft_distinguishes_not_found_from_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo)
    server.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.get_draft(draft_id, "user-1")
    server.fail_get = AppwriteException("down", code=503)
    with pytest.raises(StorageUnavailable):
        repo.get_draft(draft_id, "user-1")


def test_update_draft_only_for_owner(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo, user_id="user-1")

    assert repo.update_draft(draft_id, "user-2", last_error="x") is False
    assert server.documents[draft_id]["last_error"] is None

    assert repo.update_draft(draft_id, "user-1", last_error="rate_limited", attempt_count=3) is True
    document = server.documents[draft_id]
    assert document["last_error"] == "rate_limited"
    assert document["attempt_count"] == 3
    assert json.loads(document["form_data"]) == {"code": "DCC205", "name": "Estruturas"}

    assert repo.update_draft(draft_id, "user-1", form_data={"code": "DCC206"}) is True
    assert json.loads(server.documents[draft_id]["form_data"]) == {"code": "DCC206"}
    assert repo.update_draft("missing", "user-1", last_error="x") is False


def test_update_draft_maps_race_not_found_and_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo)
    server.fail_update = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.update_draft(draft_id, "user-1", last_error="x") is False
    server.fail_update = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.update_draft(draft_id, "user-1", last_error="x")


def test_list_drafts_filters_by_user_course_session_and_decodes(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    _save(repo, user_id="user-1", course_id="course-1", session_id="session-1")
    _save(repo, user_id="user-1", course_id="course-2", session_id="session-2")
    _save(repo, user_id="user-2", course_id="course-1", session_id="session-1")

    drafts = repo.list_drafts(user_id="user-1")
    assert len(drafts) == 2
    assert all(draft["form_data"]["code"] == "DCC205" for draft in drafts)
    assert all(draft["$id"] for draft in drafts)  # metadata merged into listed documents
    assert len(repo.list_drafts(user_id="user-2")) == 1
    assert len(repo.list_drafts(user_id="user-1", course_id="course-2")) == 1
    filtered = repo.list_drafts(user_id="user-1", course_id="course-1", session_id="session-1")
    assert len(filtered) == 1
    for queries in server.seen_queries:
        parsed = [json.loads(raw) for raw in queries]
        assert any(
            item["method"] == "equal" and item["attribute"] == "user_id" for item in parsed
        )


def test_list_drafts_requires_user_id_and_propagates_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    with pytest.raises(ValueError):
        repo.list_drafts(user_id="")
    _save(repo)
    server.fail_list = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.list_drafts(user_id="user-1")
    server.fail_list = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.list_drafts(user_id="user-1")


def test_delete_draft_only_for_owner(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo, user_id="user-1")

    assert repo.delete_draft(draft_id, "user-2") is False
    assert draft_id in server.documents
    assert repo.delete_draft(draft_id, "user-1") is True
    assert repo.delete_draft(draft_id, "user-1") is False
    server.fail_delete = AppwriteException("down", code=500)
    other = _save(repo, user_id="user-1")
    with pytest.raises(StorageUnavailable):
        repo.delete_draft(other, "user-1")


def test_get_and_list_draft_without_form_data(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo, form_data={"a": 1})
    server.documents[draft_id].pop("form_data")
    fetched = repo.get_draft(draft_id, "user-1")
    assert fetched is not None
    assert fetched["$id"] == draft_id
    assert "form_data" not in fetched
    drafts = repo.list_drafts(user_id="user-1")
    assert drafts[0].get("form_data") is None


def test_delete_draft_maps_race_not_found(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = DraftRepository(client)
    draft_id = _save(repo)
    server.fail_delete = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.delete_draft(draft_id, "user-1") is False
