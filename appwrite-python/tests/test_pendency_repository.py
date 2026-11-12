"""Tests for the Appwrite pendency persistence used by the production function."""

import copy
import json

import pytest
from appwrite.exception import AppwriteException

import pendency_repository as module
from appwrite_storage import StorageNotProvisioned, StorageUnavailable
from course_service import InvalidCourse
from pendency_repository import PendencyRepository


def parse_queries(queries):
    """Parse SDK Query JSON strings the way the Appwrite API would."""
    filters = {}
    limit = None
    offset = 0
    for raw in queries or []:
        parsed = json.loads(raw)  # every query must be valid SDK JSON
        method = parsed["method"]
        if method == "equal":
            filters[parsed["attribute"]] = parsed["values"][0]
        elif method == "limit":
            limit = parsed["values"][0]
        elif method == "offset":
            offset = parsed["values"][0]
        else:
            raise AssertionError(f"unexpected query method {method}")
    return filters, limit, offset


class FakeDatabases:
    def __init__(self, client: object) -> None:
        self.client = client
        self.documents: dict[str, dict] = {}
        self.created: list[dict] = []
        self.seen_queries: list[list[str]] = []
        self.fail_create: Exception | None = None
        self.fail_get: Exception | None = None
        self.fail_update: Exception | None = None
        self.fail_list: Exception | None = None
        self.fail_delete: Exception | None = None

    def _fail(self, error: Exception | None) -> None:
        if error is not None:
            raise error

    def create_document(self, **kwargs: object) -> dict:
        self._fail(self.fail_create)
        document = {"$id": kwargs["document_id"], **kwargs["data"]}
        self.documents[kwargs["document_id"]] = document
        self.created.append(kwargs)
        return document

    def get_document(self, **kwargs: object) -> dict:
        self._fail(self.fail_get)
        document = self.documents.get(kwargs["document_id"])
        if document is None:
            raise AppwriteException("missing", code=404, type="document_not_found")
        return copy.deepcopy(document)

    def update_document(self, **kwargs: object) -> dict:
        self._fail(self.fail_update)
        document_id = kwargs["document_id"]
        if document_id not in self.documents:
            raise AppwriteException("missing", code=404, type="document_not_found")
        self.documents[document_id].update(kwargs["data"])
        return self.documents[document_id]

    def list_documents(self, **kwargs: object) -> dict:
        self._fail(self.fail_list)
        filters, limit, offset = parse_queries(kwargs.get("queries"))
        self.seen_queries.append(list(kwargs.get("queries") or []))
        matched = [
            document
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in filters.items())
        ]
        end = None if limit is None else offset + limit
        return {"documents": copy.deepcopy(matched[offset:end]), "total": len(matched)}

    def delete_document(self, **kwargs: object) -> dict:
        self._fail(self.fail_delete)
        if kwargs["document_id"] not in self.documents:
            raise AppwriteException("missing", code=404, type="document_not_found")
        del self.documents[kwargs["document_id"]]
        return {}


@pytest.fixture()
def databases(monkeypatch: pytest.MonkeyPatch) -> FakeDatabases:
    fake = FakeDatabases(client=object())
    monkeypatch.setattr(module, "Databases", lambda client: fake)
    return fake


def _save(repo: PendencyRepository, user_id: str = "user-1", **overrides: object) -> str:
    fields = {
        "user_id": user_id,
        "course_id": "course-1",
        "course_code": "DCC205",
        "course_name": "Estruturas",
        "current_schedule": "seg 08:00 (2 aulas)",
        "new_schedule": "ter 10:00 (2 aulas)",
        "reason": "schedule_overlap",
    }
    fields.update(overrides)
    return repo.save_pendency(**fields)  # type: ignore[arg-type]


def test_save_pendency_persists_owner_fields_payload_and_permissions(
    databases: FakeDatabases,
) -> None:
    repo = PendencyRepository(client=object())
    payload = {"meetings": [{"id": "ufmg-1-480-2"}], "confirm_destructive": False}

    pendency_id = _save(repo, payload=payload)

    assert pendency_id
    created = databases.created[0]
    assert created["data"]["user_id"] == "user-1"
    assert created["data"]["course_code"] == "DCC205"
    assert created["data"]["status"] == "pending"
    assert created["data"]["decision"] is None
    assert json.loads(created["data"]["payload"]) == payload
    assert len(created["permissions"]) == 3


def test_save_pendency_without_payload_omits_field(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    _save(repo)
    assert "payload" not in databases.created[0]["data"]


def test_save_pendency_requires_user_id(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    with pytest.raises(ValueError):
        _save(repo, user_id="")


def test_save_pendency_validates_course_id(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    with pytest.raises(InvalidCourse):
        _save(repo, course_id="bad/id")


def test_save_pendency_classifies_backend_failures(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    databases.fail_create = AppwriteException("down", code=500, type="general")
    with pytest.raises(StorageUnavailable):
        _save(repo)
    databases.fail_create = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        _save(repo)


def test_get_pendency_enforces_ownership(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo, user_id="user-1")

    assert repo.get_pendency(pendency_id, "user-1")["course_code"] == "DCC205"
    assert repo.get_pendency(pendency_id, "user-2") is None
    assert repo.get_pendency("missing", "user-1") is None


def test_get_pendency_distinguishes_not_found_from_service_failure(
    databases: FakeDatabases,
) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo)
    databases.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.get_pendency(pendency_id, "user-1")
    databases.fail_get = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.get_pendency(pendency_id, "user-1")


def test_update_decision_only_for_owner(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo, user_id="user-1")

    assert repo.update_decision(pendency_id, "user-2", "manter_atual") is False
    assert databases.documents[pendency_id]["decision"] is None
    assert repo.update_decision(pendency_id, "user-1", "manter_atual") is True
    assert databases.documents[pendency_id]["decision"] == "manter_atual"
    assert databases.documents[pendency_id]["status"] == "resolved"
    assert repo.update_decision("missing", "user-1", "aplicar_mudanca") is False


def test_update_decision_maps_race_not_found_and_failures(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo)
    databases.fail_update = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.update_decision(pendency_id, "user-1", "manter_atual") is False
    databases.fail_update = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.update_decision(pendency_id, "user-1", "manter_atual")
    databases.fail_update = None
    databases.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.update_decision(pendency_id, "user-1", "manter_atual")


def test_list_pendencies_filters_by_user_course_and_status(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    _save(repo, user_id="user-1", course_id="course-1", status="pending")
    _save(repo, user_id="user-1", course_id="course-2", status="resolved")
    _save(repo, user_id="user-2", course_id="course-1", status="pending")

    assert len(repo.list_pendencies(user_id="user-1")) == 2
    assert len(repo.list_pendencies(user_id="user-2")) == 1
    only_course = repo.list_pendencies(user_id="user-1", course_id="course-2")
    assert len(only_course) == 1
    assert only_course[0]["course_id"] == "course-2"
    assert len(repo.list_pendencies(user_id="user-1", status="resolved")) == 1
    # every list call sends SDK Query JSON, including the mandatory owner filter
    for queries in databases.seen_queries:
        parsed = [json.loads(raw) for raw in queries]
        assert any(
            item["method"] == "equal" and item["attribute"] == "user_id" for item in parsed
        )


def test_list_pendencies_requires_user_id(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    with pytest.raises(ValueError):
        repo.list_pendencies(user_id="")


def test_list_pendencies_paginates_until_short_page(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    for index in range(150):
        _save(repo, course_id=f"course-{index}")
    assert len(repo.list_pendencies(user_id="user-1")) == 150
    offsets = [
        json.loads(raw)["values"][0]
        for queries in databases.seen_queries
        for raw in queries
        if json.loads(raw)["method"] == "offset"
    ]
    assert offsets == [0, 100]


def test_list_pendencies_propagates_failures_instead_of_empty_list(
    databases: FakeDatabases,
) -> None:
    repo = PendencyRepository(client=object())
    _save(repo)
    databases.fail_list = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.list_pendencies(user_id="user-1")
    databases.fail_list = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.list_pendencies(user_id="user-1")


def test_delete_pendency_only_for_owner(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo, user_id="user-1")

    assert repo.delete_pendency(pendency_id, "user-2") is False
    assert pendency_id in databases.documents
    assert repo.delete_pendency(pendency_id, "user-1") is True
    assert repo.delete_pendency(pendency_id, "user-1") is False


def test_delete_pendency_maps_race_not_found_and_failures(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    pendency_id = _save(repo)
    databases.fail_delete = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.delete_pendency(pendency_id, "user-1") is False
    databases.fail_delete = AppwriteException("down", code=503)
    with pytest.raises(StorageUnavailable):
        repo.delete_pendency(pendency_id, "user-1")


def test_get_pendency_casts_plain_document(databases: FakeDatabases) -> None:
    repo = PendencyRepository(client=object())
    databases.documents["plain"] = {"$id": "plain", "user_id": "user-1"}
    assert repo.get_pendency("plain", "user-1") == {"$id": "plain", "user_id": "user-1"}
