"""Tests for the Appwrite registration-draft persistence used by the production function."""

import json

import pytest

import draft_repository as module
from course_service import InvalidCourse
from draft_repository import DraftRepository


class FakeDatabases:
    def __init__(self, client: object) -> None:
        self.documents: dict[str, dict] = {}
        self.created: list[dict] = []
        self.fail_create = False

    def create_document(self, **kwargs: object) -> dict:
        if self.fail_create:
            raise RuntimeError("appwrite down")
        document = {"$id": kwargs["document_id"], **kwargs["data"]}
        self.documents[kwargs["document_id"]] = document
        self.created.append(kwargs)
        return document

    def get_document(self, **kwargs: object) -> dict:
        if kwargs["document_id"] not in self.documents:
            raise RuntimeError("not found")
        return self.documents[kwargs["document_id"]]

    def update_document(self, **kwargs: object) -> dict:
        document_id = kwargs["document_id"]
        if document_id not in self.documents:
            raise RuntimeError("not found")
        self.documents[document_id].update(kwargs["data"])
        return self.documents[document_id]

    def list_documents(self, **kwargs: object) -> dict:
        if getattr(self, "fail_list", False):
            raise RuntimeError("list failed")
        return {"documents": list(self.documents.values())}

    def delete_document(self, **kwargs: object) -> dict:
        if kwargs["document_id"] not in self.documents:
            raise RuntimeError("not found")
        del self.documents[kwargs["document_id"]]
        return {}


@pytest.fixture()
def databases(monkeypatch: pytest.MonkeyPatch) -> FakeDatabases:
    fake = FakeDatabases(client=object())
    monkeypatch.setattr(module, "Databases", lambda client: fake)
    return fake


def test_save_and_get_draft_round_trips_form_data(databases: FakeDatabases) -> None:
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
    assert json.loads(created["form_data"]) == form_data
    assert created["last_error"] == "rate_limited"
    assert created["attempt_count"] == 2
    assert len(databases.created[0]["permissions"]) == 3

    fetched = repo.get_draft(draft_id)
    assert fetched is not None
    assert fetched["form_data"] == form_data
    assert repo.get_draft("missing") is None


def test_save_draft_validates_course_and_reraises(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    with pytest.raises(InvalidCourse):
        repo.save_draft(
            user_id="user-1",
            course_id="bad/id",
            course_code="X",
            session_id="s",
            form_data={},
        )
    databases.fail_create = True
    with pytest.raises(RuntimeError):
        repo.save_draft(
            user_id="user-1",
            course_id="course-1",
            course_code="X",
            session_id="s",
            form_data={},
        )


def test_update_draft_merges_only_provided_fields(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = repo.save_draft(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        session_id="session-1",
        form_data={"code": "DCC205"},
    )
    assert repo.update_draft(draft_id, last_error="rate_limited", attempt_count=3) is True
    document = databases.documents[draft_id]
    assert document["last_error"] == "rate_limited"
    assert document["attempt_count"] == 3
    assert json.loads(document["form_data"]) == {"code": "DCC205"}

    assert repo.update_draft(draft_id, form_data={"code": "DCC206"}) is True
    assert json.loads(databases.documents[draft_id]["form_data"]) == {"code": "DCC206"}
    assert repo.update_draft("missing", last_error="x") is False


def test_list_drafts_decodes_form_data_and_handles_failure(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    repo.save_draft(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        session_id="session-1",
        form_data={"code": "DCC205"},
    )
    drafts = repo.list_drafts(course_id="course-1", session_id="session-1")
    assert len(drafts) == 1
    assert drafts[0]["form_data"] == {"code": "DCC205"}

    databases.fail_list = True
    assert repo.list_drafts() == []


def test_delete_draft(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    draft_id = repo.save_draft(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        session_id="session-1",
        form_data={},
    )
    assert repo.delete_draft(draft_id) is True
    assert repo.delete_draft(draft_id) is False


def test_get_draft_without_form_data_and_list_without_form_data(
    databases: FakeDatabases,
) -> None:
    repo = DraftRepository(client=object())
    draft_id = repo.save_draft(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        session_id="s1",
        form_data={"a": 1},
    )
    databases.documents[draft_id].pop("form_data")
    assert repo.get_draft(draft_id)["$id"] == draft_id
    drafts = repo.list_drafts()
    assert drafts[0].get("form_data") is None


def test_get_draft_returns_empty_document_when_present(databases: FakeDatabases) -> None:
    repo = DraftRepository(client=object())
    databases.documents["empty"] = {}
    assert repo.get_draft("empty") == {}
