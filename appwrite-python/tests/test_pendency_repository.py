"""Tests for the Appwrite pendency persistence used by the production function."""

import json

import pytest

import pendency_repository as module
from course_service import InvalidCourse
from pendency_repository import PendencyRepository


class FakeDatabases:
    def __init__(self, client: object) -> None:
        self.client = client
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


def test_save_pendency_persists_fields_payload_and_user_permissions(
    databases: FakeDatabases,
) -> None:
    repo = PendencyRepository(client=object())
    payload = {"meetings": [{"id": "ufmg-1-480-2"}], "confirm_destructive": True}

    pendency_id = repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="seg 08:00 (2 aulas)",
        new_schedule="ter 10:00 (2 aulas)",
        reason="manual_schedule_diverged",
        payload=payload,
    )

    assert pendency_id
    created = databases.created[0]
    assert created["data"]["course_code"] == "DCC205"
    assert created["data"]["status"] == "pending"
    assert created["data"]["decision"] is None
    assert json.loads(created["data"]["payload"]) == payload
    permissions = created["permissions"]
    assert len(permissions) == 3


def test_save_pendency_without_payload_omits_field(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="seg 08:00 (2 aulas)",
        new_schedule="ter 10:00 (2 aulas)",
        reason="schedule_overlap",
    )
    assert "payload" not in databases.created[0]["data"]


def test_save_pendency_validates_course_id(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    with pytest.raises(InvalidCourse):
        repo.save_pendency(
            user_id="user-1",
            course_id="bad/id",
            course_code="X",
            course_name="X",
            current_schedule="a",
            new_schedule="b",
            reason="r",
        )


def test_save_pendency_reraises_on_backend_failure(databases: FakeDatabases) -> None:
    databases.fail_create = True
    repo = PendencyRepository(client=object())
    with pytest.raises(RuntimeError):
        repo.save_pendency(
            user_id="user-1",
            course_id="course-1",
            course_code="X",
            course_name="X",
            current_schedule="a",
            new_schedule="b",
            reason="r",
        )


def test_get_pendency_returns_document_or_none(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="a",
        new_schedule="b",
        reason="r",
    )
    assert repo.get_pendency(pendency_id)["course_code"] == "DCC205"
    assert repo.get_pendency("missing") is None


def test_update_decision_persists_resolution(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="a",
        new_schedule="b",
        reason="r",
    )
    assert repo.update_decision(pendency_id, "manter_atual") is True
    assert databases.documents[pendency_id]["decision"] == "manter_atual"
    assert databases.documents[pendency_id]["status"] == "resolved"
    assert repo.update_decision("missing", "aplicar_mudanca") is False


def test_list_pendencies_builds_queries_and_casts(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="a",
        new_schedule="b",
        reason="r",
    )
    assert len(repo.list_pendencies(course_id="course-1", status="pending")) == 1
    databases.fail_list = True
    assert repo.list_pendencies() == []


def test_delete_pendency(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = repo.save_pendency(
        user_id="user-1",
        course_id="course-1",
        course_code="DCC205",
        course_name="Estruturas",
        current_schedule="a",
        new_schedule="b",
        reason="r",
    )
    assert repo.delete_pendency(pendency_id) is True
    assert repo.delete_pendency(pendency_id) is False


def test_get_pendency_casts_plain_document(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    databases.documents["plain"] = {"$id": "plain"}
    assert repo.get_pendency("plain") == {"$id": "plain"}
