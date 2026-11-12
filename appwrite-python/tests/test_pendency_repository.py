"""Tests for the Appwrite pendency persistence used by the production function.

The real Appwrite SDK 27.1.0 services run against a fake HTTP transport: only
``client.call`` is monkeypatched, so canned responses travel through the real
``Document``/``DocumentList`` models exactly like in production.
"""

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from appwrite.client import Client
from appwrite.exception import AppwriteException

from appwrite_storage import (
    LIST_PAGE_SIZE,
    PENDENCY_COLLECTION_ID,
    StorageNotProvisioned,
    StorageUnavailable,
)
from course_service import InvalidCourse
from pendency_repository import PendencyRepository

TransportHandler = Callable[[str, str, dict[str, Any]], dict[str, Any]]


# Explicit database id used by the fakes; the runtime never defaults one.
TEST_DATABASE_ID = "test-database"


class FakeTransport:
    """Stand-in for ``Client.call``: records the request, replays canned HTTP JSON."""

    def __init__(self, handler: TransportHandler) -> None:
        self.handler = handler
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        method: str,
        path: str = "",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        response_type: str = "json",
    ) -> Any:
        self.calls.append({"method": method, "path": path, "params": params or {}})
        return self.handler(method, path, params or {})


def make_client(
    monkeypatch: pytest.MonkeyPatch, handler: TransportHandler
) -> tuple[Client, FakeTransport]:
    """Build a real SDK client whose HTTP transport is the given handler."""
    client = Client().set_endpoint("https://cloud.appwrite.io/v1").set_project("proj")
    transport = FakeTransport(handler)
    monkeypatch.setattr(client, "call", transport)
    return client, transport


def parse_queries(queries: list[str] | None) -> tuple[dict[str, Any], int | None, int]:
    """Parse SDK Query JSON strings the way the Appwrite API would."""
    filters: dict[str, Any] = {}
    limit: int | None = None
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


def document_json(
    document_id: str,
    data: dict[str, Any],
    *,
    collection_id: str,
    database_id: str,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    """Flat HTTP document JSON as the Appwrite API returns it."""
    return {
        "$id": document_id,
        "$sequence": "1",
        "$collectionId": collection_id,
        "$databaseId": database_id,
        "$createdAt": "2025-01-01T00:00:00.000+00:00",
        "$updatedAt": "2025-01-01T00:00:00.000+00:00",
        "$permissions": permissions or [],
        **data,
    }




def _translate_tablesdb_path(path: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Map a TablesDB row path onto the legacy shape this fake handles."""
    rest = path[len("/tablesdb/"):]
    db, _, tail = rest.partition("/tables/")
    table, _, resource = tail.partition("/rows")
    if resource == "":
        legacy = f"/databases/{db}/collections/{table}/documents"
    else:
        legacy = f"/databases/{db}/collections/{table}/documents/{resource.lstrip('/')}"
    params = dict(params)
    if "rowId" in params:
        params["documentId"] = params.pop("rowId")
    return legacy, params


def _translate_tablesdb_response(resp: Any) -> Any:
    """RowList expects ``rows``; Row metadata uses ``$tableId``."""
    if isinstance(resp, dict):
        resp = dict(resp)
        if "documents" in resp:
            resp["rows"] = [
                {("$tableId" if k == "$collectionId" else k): v for k, v in doc.items()}
                for doc in resp.pop("documents")
            ]
        elif "$collectionId" in resp:
            resp = {("$tableId" if k == "$collectionId" else k): v for k, v in resp.items()}
    return resp


def _translate_tablesdb_error(error: AppwriteException) -> AppwriteException:
    if error.code == 404 and getattr(error, "type", None) == "document_not_found":
        return AppwriteException(error.message, code=404, type="row_not_found")
    if error.code == 404 and getattr(error, "type", None) == "collection_not_found":
        return AppwriteException(error.message, code=404, type="table_not_found")
    return error


class DocumentServer:
    """In-memory document store served as canned ``client.call`` HTTP JSON."""

    def __init__(
        self, database_id: str = TEST_DATABASE_ID, collection_id: str = PENDENCY_COLLECTION_ID
    ) -> None:
        self.database_id = database_id
        self.collection_id = collection_id
        self.documents: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.seen_queries: list[list[str]] = []
        self.fail_create: Exception | None = None
        self.fail_get: Exception | None = None
        self.fail_update: Exception | None = None
        self.fail_list: Exception | None = None
        self.fail_delete: Exception | None = None

    def _fail(self, error: Exception | None) -> None:
        if error is not None:
            raise error

    @staticmethod
    def _not_found() -> AppwriteException:
        return AppwriteException("missing", code=404, type="document_not_found")

    @property
    def documents_path(self) -> str:
        return f"/databases/{self.database_id}/collections/{self.collection_id}/documents"

    def __call__(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        is_tables = path.startswith("/tablesdb/")
        if is_tables:
            path, params = _translate_tablesdb_path(path, params)
        try:
            resp = self._handle(method, path, params)
        except AppwriteException as error:
            if is_tables:
                raise _translate_tablesdb_error(error) from None
            raise
        if is_tables:
            return _translate_tablesdb_response(resp)
        return resp

    def _handle(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        docs = self.documents_path
        if path == docs and method == "post":
            self._fail(self.fail_create)
            document = document_json(
                params["documentId"],
                params["data"],
                collection_id=self.collection_id,
                database_id=self.database_id,
                permissions=params.get("permissions"),
            )
            self.documents[params["documentId"]] = document
            self.created.append(dict(params))
            return document
        if path == docs and method == "get":
            self._fail(self.fail_list)
            self.seen_queries.append(list(params.get("queries") or []))
            filters, limit, offset = parse_queries(params.get("queries"))
            matched = [
                document
                for document in self.documents.values()
                if all(document.get(key) == value for key, value in filters.items())
            ]
            end = None if limit is None else offset + limit
            return {"total": len(matched), "documents": copy.deepcopy(matched[offset:end])}
        prefix = f"{docs}/"
        if path.startswith(prefix):
            document_id = path[len(prefix) :]
            if method == "get":
                self._fail(self.fail_get)
                document = self.documents.get(document_id)
                if document is None:
                    raise self._not_found()
                return copy.deepcopy(document)
            if method == "patch":
                self._fail(self.fail_update)
                if document_id not in self.documents:
                    raise self._not_found()
                self.documents[document_id].update(params["data"])
                return copy.deepcopy(self.documents[document_id])
            if method == "delete":
                self._fail(self.fail_delete)
                if document_id not in self.documents:
                    raise self._not_found()
                del self.documents[document_id]
                return {}
        raise AssertionError(f"unexpected transport call {method} {path}")


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Client, DocumentServer, FakeTransport]:
    server = DocumentServer()
    client, transport = make_client(monkeypatch, server)
    return client, server, transport


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
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, transport = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    payload = {"meetings": [{"id": "ufmg-1-480-2"}], "confirm_destructive": False}

    pendency_id = _save(repo, payload=payload)

    assert pendency_id
    assert transport.calls[0]["method"] == "post"
    rows_path = f"/tablesdb/{TEST_DATABASE_ID}/tables/{PENDENCY_COLLECTION_ID}/rows"
    assert transport.calls[0]["path"] == rows_path
    created = server.created[0]
    assert created["documentId"] == pendency_id
    assert created["data"]["user_id"] == "user-1"
    assert created["data"]["course_code"] == "DCC205"
    assert created["data"]["status"] == "pending"
    assert created["data"]["decision"] is None
    assert json.loads(created["data"]["payload"]) == payload
    assert created["permissions"] == [
        'read("user:user-1")',
        'write("user:user-1")',
        'delete("user:user-1")',
    ]


def test_save_pendency_without_payload_omits_field(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    _save(repo)
    assert "payload" not in server.created[0]["data"]


def test_save_pendency_requires_user_id(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, _, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    with pytest.raises(ValueError):
        _save(repo, user_id="")


def test_save_pendency_validates_course_id(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, _, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    with pytest.raises(InvalidCourse):
        _save(repo, course_id="bad/id")


def test_save_pendency_classifies_backend_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    server.fail_create = AppwriteException("down", code=500, type="general")
    with pytest.raises(StorageUnavailable):
        _save(repo)
    server.fail_create = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        _save(repo)


def test_get_pendency_enforces_ownership_and_merges_sdk_document(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, _, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo, user_id="user-1")

    fetched = repo.get_pendency(pendency_id, "user-1")
    assert fetched is not None
    # metadata is preserved and the SDK-nested data is merged at the top level
    assert fetched["$id"] == pendency_id
    assert fetched["$tableId"] == PENDENCY_COLLECTION_ID
    assert fetched["$databaseId"] == TEST_DATABASE_ID
    assert fetched["$permissions"] == [
        'read("user:user-1")',
        'write("user:user-1")',
        'delete("user:user-1")',
    ]
    assert fetched["user_id"] == "user-1"
    assert fetched["course_code"] == "DCC205"
    assert "data" not in fetched
    assert repo.get_pendency(pendency_id, "user-2") is None
    assert repo.get_pendency("missing", "user-1") is None


def test_get_pendency_distinguishes_not_found_from_service_failure(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo)
    server.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.get_pendency(pendency_id, "user-1")
    server.fail_get = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.get_pendency(pendency_id, "user-1")


def test_update_decision_only_for_owner(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo, user_id="user-1")

    assert repo.update_decision(pendency_id, "user-2", "manter_atual") is False
    assert server.documents[pendency_id]["decision"] is None
    assert repo.update_decision(pendency_id, "user-1", "manter_atual") is True
    assert server.documents[pendency_id]["decision"] == "manter_atual"
    assert server.documents[pendency_id]["status"] == "resolved"
    assert repo.update_decision("missing", "user-1", "aplicar_mudanca") is False


def test_update_decision_maps_race_not_found_and_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo)
    server.fail_update = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.update_decision(pendency_id, "user-1", "manter_atual") is False
    server.fail_update = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.update_decision(pendency_id, "user-1", "manter_atual")
    server.fail_update = None
    server.fail_get = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.update_decision(pendency_id, "user-1", "manter_atual")


def test_list_pendencies_filters_by_user_course_and_status(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    _save(repo, user_id="user-1", course_id="course-1", status="pending")
    _save(repo, user_id="user-1", course_id="course-2", status="resolved")
    _save(repo, user_id="user-2", course_id="course-1", status="pending")

    assert len(repo.list_pendencies(user_id="user-1")) == 2
    assert len(repo.list_pendencies(user_id="user-2")) == 1
    only_course = repo.list_pendencies(user_id="user-1", course_id="course-2")
    assert len(only_course) == 1
    assert only_course[0]["course_id"] == "course-2"
    assert only_course[0]["$id"]  # metadata merged into listed documents
    assert len(repo.list_pendencies(user_id="user-1", status="resolved")) == 1
    # every list call sends SDK Query JSON, including the mandatory owner filter
    for queries in server.seen_queries:
        parsed = [json.loads(raw) for raw in queries]
        assert any(
            item["method"] == "equal" and item["attribute"] == "user_id" for item in parsed
        )
        assert any(
            item["method"] == "limit" and item["values"] == [LIST_PAGE_SIZE] for item in parsed
        )
        assert any(item["method"] == "offset" for item in parsed)


def test_list_pendencies_requires_user_id(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, _, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    with pytest.raises(ValueError):
        repo.list_pendencies(user_id="")


def test_list_pendencies_paginates_until_short_page(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    for index in range(LIST_PAGE_SIZE + 50):
        _save(repo, course_id=f"course-{index}")
    result = repo.list_pendencies(user_id="user-1")
    assert len(result) == LIST_PAGE_SIZE + 50
    assert all(document["user_id"] == "user-1" for document in result)
    offsets = [
        json.loads(raw)["values"][0]
        for queries in server.seen_queries
        for raw in queries
        if json.loads(raw)["method"] == "offset"
    ]
    assert offsets == [0, LIST_PAGE_SIZE]


def test_list_pendencies_propagates_failures_instead_of_empty_list(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    _save(repo)
    server.fail_list = AppwriteException("down", code=500)
    with pytest.raises(StorageUnavailable):
        repo.list_pendencies(user_id="user-1")
    server.fail_list = AppwriteException("missing", code=404, type="collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        repo.list_pendencies(user_id="user-1")


def test_delete_pendency_only_for_owner(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo, user_id="user-1")

    assert repo.delete_pendency(pendency_id, "user-2") is False
    assert pendency_id in server.documents
    assert repo.delete_pendency(pendency_id, "user-1") is True
    assert repo.delete_pendency(pendency_id, "user-1") is False


def test_delete_pendency_maps_race_not_found_and_failures(
    harness: tuple[Client, DocumentServer, FakeTransport],
) -> None:
    client, server, _ = harness
    repo = PendencyRepository(client, database_id=TEST_DATABASE_ID)
    pendency_id = _save(repo)
    server.fail_delete = AppwriteException("gone", code=404, type="document_not_found")
    assert repo.delete_pendency(pendency_id, "user-1") is False
    server.fail_delete = AppwriteException("down", code=503)
    with pytest.raises(StorageUnavailable):
        repo.delete_pendency(pendency_id, "user-1")
