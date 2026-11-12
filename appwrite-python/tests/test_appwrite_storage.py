"""Tests for the Appwrite storage adapter: error taxonomy, pagination, normalization.

The real Appwrite SDK 27.1.0 services run against a fake HTTP transport: only
``client.call`` is monkeypatched, so canned responses travel through the real
``Database``/``DocumentList`` models exactly like in production. Schema
provisioning lives in the operator-only storage_schema module and is covered
in test_storage_schema.py.
"""

import copy
import json
from typing import Any

import pytest
from appwrite.exception import AppwriteException
from appwrite.models import Document
from appwrite.query import Query
from appwrite.services.databases import Databases
from test_pendency_repository import (
    FakeTransport,
    document_json,
    make_client,
    parse_queries,
)

from appwrite_storage import (
    LIST_PAGE_SIZE,
    PENDENCY_COLLECTION_ID,
    StorageNotFound,
    StorageNotProvisioned,
    StorageUnavailable,
    classify_error,
    list_all_documents,
    normalize_document,
)

STAMP = "2025-01-01T00:00:00.000+00:00"

# Explicit target database used by the fakes; the runtime never defaults one.
TEST_DATABASE_ID = "test-database"


def database_json(database_id: str) -> dict[str, Any]:
    return {
        "$id": database_id,
        "name": database_id,
        "$createdAt": STAMP,
        "$updatedAt": STAMP,
        "enabled": True,
    }


def collection_json(collection_id: str, name: str) -> dict[str, Any]:
    return {
        "$id": collection_id,
        "name": name,
        "$createdAt": STAMP,
        "$updatedAt": STAMP,
    }


def attribute_json(
    key: str,
    type_: str,
    *,
    required: bool = True,
    size: float = 128.0,
    status: str = "available",
    error: str = "",
) -> dict[str, Any]:
    attribute: dict[str, Any] = {
        "$id": key,
        "key": key,
        "description": "",
        "type": type_,
        "status": status,
        "error": error,
        "required": required,
        "$createdAt": STAMP,
        "$updatedAt": STAMP,
    }
    if type_ == "string":
        attribute["size"] = size
    else:
        attribute.update({"min": 0.0, "max": 1000.0, "default": 0.0})
    return attribute


def index_json(
    key: str, attributes: list[str], *, status: str = "available", error: str = ""
) -> dict[str, Any]:
    return {
        "$id": key,
        "$createdAt": STAMP,
        "$updatedAt": STAMP,
        "key": key,
        "description": "",
        "type": "key",
        "status": status,
        "error": error,
        "attributes": attributes,
        "lengths": [],
        "orders": [],
    }


class StorageServer:
    """Provisioning + document endpoints served as canned ``client.call`` HTTP JSON."""

    def __init__(self, database_id: str = TEST_DATABASE_ID) -> None:
        self.database_id = database_id
        self.databases: set[str] = set()
        self.collections: dict[str, dict[str, Any]] = {}
        self.attributes: dict[str, dict[str, str]] = {}
        self.indexes: dict[str, dict[str, list[str]]] = {}
        self.attribute_meta: dict[tuple[str, str], tuple[str, str]] = {}
        self.index_meta: dict[tuple[str, str], tuple[str, str]] = {}
        self.on_list_attributes = None
        self.on_list_indexes = None
        self.new_attributes_processing = False
        self.attribute_ready_at_index_create: list[bool] = []
        self.documents: dict[str, dict[str, dict[str, Any]]] = {}
        self.create_collection_calls: list[dict[str, Any]] = []
        self.full_pages_only = False
        self.fail_get_db: Exception | None = None
        self.fail_create_db: Exception | None = None
        self.fail_get_collection: Exception | None = None
        self.fail_create_collection: Exception | None = None
        self.fail_list_attributes: Exception | None = None
        self.fail_create_attribute: Exception | None = None
        self.fail_list_indexes: Exception | None = None
        self.fail_create_index: Exception | None = None
        self.fail_list_documents: Exception | None = None

    def _fail(self, error: Exception | None) -> None:
        if error is not None:
            raise error

    def _fail_create(self, error: Exception | None, register) -> None:
        """A 409 race means a concurrent provisioner created the resource first."""
        if error is None:
            register()
        elif getattr(error, "code", None) == 409:
            register()
            raise error
        else:
            raise error

    def add_collection(self, collection_id: str, spec: dict[str, Any] | None = None) -> None:
        spec = spec or {"name": collection_id, "attributes": [], "indexes": []}
        self.collections[collection_id] = {"name": spec["name"]}
        self.attributes[collection_id] = {a["key"]: a["type"] for a in spec["attributes"]}
        self.indexes[collection_id] = {i["key"]: list(i["attributes"]) for i in spec["indexes"]}
        self.documents[collection_id] = {}

    def __call__(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        prefix = f"/databases/{self.database_id}"
        if path == "/databases" and method == "post":
            self._fail(self.fail_create_db)
            if params["databaseId"] in self.databases:
                raise AppwriteException("exists", code=409, type="database_already_exists")
            self.databases.add(params["databaseId"])
            return database_json(params["databaseId"])
        if path == prefix and method == "get":
            self._fail(self.fail_get_db)
            if self.database_id not in self.databases:
                raise AppwriteException("missing", code=404, type="database_not_found")
            return database_json(self.database_id)
        if path == f"{prefix}/collections" and method == "post":
            self.create_collection_calls.append(dict(params))
            self._fail(self.fail_create_collection)
            collection_id = params["collectionId"]
            if collection_id in self.collections:
                raise AppwriteException("exists", code=409, type="collection_already_exists")
            self.add_collection(
                collection_id,
                {
                    "name": params["name"],
                    "attributes": params.get("attributes", []),
                    "indexes": params.get("indexes", []),
                },
            )
            return collection_json(collection_id, params["name"])
        collections_prefix = f"{prefix}/collections/"
        if not path.startswith(collections_prefix):
            raise AssertionError(f"unexpected transport call {method} {path}")
        collection_id, _, resource = path[len(collections_prefix) :].partition("/")
        if resource == "" and method == "get":
            self._fail(self.fail_get_collection)
            if self.database_id not in self.databases:
                raise AppwriteException("missing", code=404, type="database_not_found")
            if collection_id not in self.collections:
                raise AppwriteException("missing", code=404, type="collection_not_found")
            return collection_json(collection_id, self.collections[collection_id]["name"])
        if collection_id not in self.collections:
            raise AppwriteException("missing", code=404, type="collection_not_found")
        return self._collection_resource(method, collection_id, resource, params)

    def _collection_resource(
        self, method: str, collection_id: str, resource: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if resource == "attributes" and method == "get":
            self._fail(self.fail_list_attributes)
            if self.on_list_attributes is not None:
                self.on_list_attributes(collection_id)
            attributes = [
                attribute_json(
                    key,
                    type_,
                    status=self.attribute_meta.get((collection_id, key), ("available", ""))[0],
                    error=self.attribute_meta.get((collection_id, key), ("available", ""))[1],
                )
                for key, type_ in self.attributes[collection_id].items()
            ]
            return {"total": len(attributes), "attributes": attributes}
        if resource == "attributes/string" and method == "post":
            key = params["key"]
            if key in self.attributes[collection_id]:
                self._fail(self.fail_create_attribute)
                raise AppwriteException("exists", code=409, type="attribute_already_exists")

            def register_string() -> None:
                self.attributes[collection_id][key] = "string"
                if self.new_attributes_processing:
                    self.attribute_meta[(collection_id, key)] = ("processing", "still building")

            self._fail_create(self.fail_create_attribute, register_string)
            return attribute_json(key, "string", required=params["required"], size=params["size"])
        if resource == "attributes/integer" and method == "post":
            key = params["key"]
            if key in self.attributes[collection_id]:
                self._fail(self.fail_create_attribute)
                raise AppwriteException("exists", code=409, type="attribute_already_exists")

            def register_integer() -> None:
                self.attributes[collection_id][key] = "integer"
                if self.new_attributes_processing:
                    self.attribute_meta[(collection_id, key)] = ("processing", "still building")

            self._fail_create(self.fail_create_attribute, register_integer)
            return attribute_json(key, "integer", required=params["required"])
        if resource == "indexes" and method == "get":
            self._fail(self.fail_list_indexes)
            if self.on_list_indexes is not None:
                self.on_list_indexes(collection_id)
            indexes = [
                index_json(
                    key,
                    attributes,
                    status=self.index_meta.get((collection_id, key), ("available", ""))[0],
                    error=self.index_meta.get((collection_id, key), ("available", ""))[1],
                )
                for key, attributes in self.indexes[collection_id].items()
            ]
            return {"total": len(indexes), "indexes": indexes}
        if resource == "indexes" and method == "post":
            key = params["key"]
            if key in self.indexes[collection_id]:
                self._fail(self.fail_create_index)
                raise AppwriteException("exists", code=409, type="index_already_exists")

            def register_index() -> None:
                self.indexes[collection_id][key] = list(params["attributes"])

            self._fail_create(self.fail_create_index, register_index)
            self.attribute_ready_at_index_create.append(
                all(
                    self.attribute_meta.get((collection_id, attribute_key), ("available", ""))[0]
                    == "available"
                    for attribute_key in self.attributes[collection_id]
                )
            )
            return index_json(key, params["attributes"])
        if resource == "documents" and method == "get":
            self._fail(self.fail_list_documents)
            filters, limit, offset = parse_queries(params.get("queries"))
            matched = [
                document
                for document in self.documents[collection_id].values()
                if all(document.get(key) == value for key, value in filters.items())
            ]
            if self.full_pages_only:
                page = matched[:LIST_PAGE_SIZE]  # never a short page: pagination never ends
            else:
                end = None if limit is None else offset + limit
                page = matched[offset:end]
            return {"total": len(matched), "documents": copy.deepcopy(page)}
        raise AssertionError(f"unexpected transport call {method} {resource}")


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Databases, StorageServer, FakeTransport]:
    server = StorageServer()
    client, transport = make_client(monkeypatch, server)
    return Databases(client), server, transport


def _err(code: int, type: str | None = None) -> AppwriteException:
    return AppwriteException("boom", code=code, type=type)


def test_classify_error_covers_the_whole_taxonomy() -> None:
    assert isinstance(
        classify_error(_err(404, "collection_not_found"), operation="op", document_level=True),
        StorageNotProvisioned,
    )
    assert isinstance(
        classify_error(_err(404, "database_not_found"), operation="op", document_level=False),
        StorageNotProvisioned,
    )
    assert isinstance(
        classify_error(_err(404, "document_not_found"), operation="op", document_level=True),
        StorageNotFound,
    )
    assert isinstance(
        classify_error(_err(404, None), operation="op", document_level=True), StorageNotFound
    )
    assert isinstance(
        classify_error(_err(404, "document_not_found"), operation="op", document_level=False),
        StorageNotProvisioned,
    )
    assert isinstance(
        classify_error(_err(404, "weird"), operation="op", document_level=False),
        StorageNotProvisioned,
    )
    assert isinstance(
        classify_error(_err(500, "general"), operation="op", document_level=True),
        StorageUnavailable,
    )

    assert isinstance(
        classify_error(_err(401, "invalid_credentials"), operation="op", document_level=False),
        StorageUnavailable,
    )
    assert isinstance(
        classify_error(_err(403, "unauthorized_scope"), operation="op", document_level=True),
        StorageUnavailable,
    )


def test_normalize_document_flattens_a_real_sdk_document() -> None:
    document = Document.with_data(
        {
            "$id": "doc-1",
            "$permissions": ['read("user:user-1")'],
            "$createdAt": STAMP,
            "user_id": "user-1",
            "course_id": "course-1",
        },
        dict,
    )
    assert document.to_dict()["data"] == {"user_id": "user-1", "course_id": "course-1"}

    flat = normalize_document(document)

    assert flat["$id"] == "doc-1"
    assert flat["$permissions"] == ['read("user:user-1")']
    assert flat["$createdAt"] == STAMP
    assert flat["user_id"] == "user-1"
    assert flat["course_id"] == "course-1"
    assert "data" not in flat


def test_list_all_documents_paginates_and_applies_sdk_queries(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, transport = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)
    total = 2 * LIST_PAGE_SIZE + 50
    for index in range(total):
        document_id = f"doc-{index}"
        server.documents[PENDENCY_COLLECTION_ID][document_id] = document_json(
            document_id,
            {"user_id": "user-1" if index % 2 else "user-2"},
            collection_id=PENDENCY_COLLECTION_ID,
            database_id=TEST_DATABASE_ID,
        )

    result = list_all_documents(
        databases, TEST_DATABASE_ID, PENDENCY_COLLECTION_ID, [Query.equal("user_id", "user-1")]
    )

    assert len(result) == sum(1 for index in range(total) if index % 2)  # 125 of 250
    assert all(document["user_id"] == "user-1" for document in result)
    assert all(document["$id"].startswith("doc-") for document in result)  # metadata merged
    list_calls = [
        call
        for call in transport.calls
        if call["method"] == "get" and call["path"].endswith("/documents")
    ]
    assert len(list_calls) == 2  # one full page + one short page
    offsets = [
        json.loads(raw)["values"][0]
        for call in list_calls
        for raw in call["params"]["queries"]
        if json.loads(raw)["method"] == "offset"
    ]
    assert offsets == [0, LIST_PAGE_SIZE]
    first_queries = [json.loads(raw) for raw in list_calls[0]["params"]["queries"]]
    assert {"method": "equal", "attribute": "user_id", "values": ["user-1"]} in first_queries


def test_list_all_documents_raises_on_service_failure_and_missing_collection(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)
    server.fail_list_documents = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        list_all_documents(databases, TEST_DATABASE_ID, PENDENCY_COLLECTION_ID, [])
    server.fail_list_documents = _err(404, "collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        list_all_documents(databases, TEST_DATABASE_ID, PENDENCY_COLLECTION_ID, [])


def test_list_all_documents_budgets_infinite_pages(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)
    for index in range(LIST_PAGE_SIZE):
        server.documents[PENDENCY_COLLECTION_ID][f"doc-{index}"] = document_json(
            f"doc-{index}",
            {"user_id": "user-1"},
            collection_id=PENDENCY_COLLECTION_ID,
            database_id=TEST_DATABASE_ID,
        )
    server.full_pages_only = True  # every page is full, so the budget must trip
    with pytest.raises(StorageUnavailable):
        list_all_documents(databases, TEST_DATABASE_ID, PENDENCY_COLLECTION_ID, [])


