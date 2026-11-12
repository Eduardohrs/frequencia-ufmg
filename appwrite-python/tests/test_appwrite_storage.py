"""Tests for the Appwrite storage taxonomy, pagination, and provisioning."""

import json

import pytest
from appwrite.exception import AppwriteException

from appwrite_storage import (
    COLLECTION_SPECS,
    DATABASE_ID,
    DRAFT_COLLECTION_ID,
    LIST_PAGE_SIZE,
    PENDENCY_COLLECTION_ID,
    StorageNotFound,
    StorageNotProvisioned,
    StorageUnavailable,
    classify_error,
    ensure_appwrite_storage,
    list_all_documents,
    validate_appwrite_storage,
)


def _err(code: int, type: str | None = None) -> AppwriteException:
    return AppwriteException("boom", code=code, type=type)


class FakeDatabases:
    """In-memory stand-in for the SDK Databases service."""

    def __init__(self) -> None:
        self.databases: set[str] = set()
        self.collections: dict[str, dict] = {}
        self.attributes: dict[str, set[str]] = {}
        self.indexes: dict[str, set[str]] = {}
        self.documents: dict[str, dict[str, dict]] = {}
        self.fail_get_db: Exception | None = None
        self.fail_create_db: Exception | None = None
        self.fail_get_collection: Exception | None = None
        self.fail_create_collection: Exception | None = None
        self.fail_list_attributes: Exception | None = None
        self.fail_create_attribute: Exception | None = None
        self.fail_list_indexes: Exception | None = None
        self.fail_create_index: Exception | None = None
        self.fail_list_documents: Exception | None = None
        self.create_collection_calls: list[dict] = []

    def get(self, database_id: str) -> dict:
        if self.fail_get_db is not None:
            raise self.fail_get_db
        if database_id not in self.databases:
            raise _err(404, "database_not_found")
        return {"$id": database_id}

    def create(self, database_id: str, name: str) -> dict:
        if self.fail_create_db is not None:
            raise self.fail_create_db
        if database_id in self.databases:
            raise _err(409, "database_already_exists")
        self.databases.add(database_id)
        return {"$id": database_id, "name": name}

    def get_collection(self, database_id: str, collection_id: str) -> dict:
        if self.fail_get_collection is not None:
            raise self.fail_get_collection
        if database_id not in self.databases:
            raise _err(404, "database_not_found")
        if collection_id not in self.collections:
            raise _err(404, "collection_not_found")
        return {"$id": collection_id}

    def create_collection(
        self, database_id: str, collection_id: str, name: str, **kwargs: object
    ) -> dict:
        self.create_collection_calls.append(
            {"database_id": database_id, "collection_id": collection_id, "name": name, **kwargs}
        )
        if self.fail_create_collection is not None:
            raise self.fail_create_collection
        if collection_id in self.collections:
            raise _err(409, "collection_already_exists")
        self.collections[collection_id] = {"name": name}
        self.attributes[collection_id] = {str(attr["key"]) for attr in kwargs.get("attributes", [])}
        self.indexes[collection_id] = {str(idx["key"]) for idx in kwargs.get("indexes", [])}
        self.documents[collection_id] = {}
        return {"$id": collection_id}

    def list_attributes(self, database_id: str, collection_id: str) -> dict:
        if self.fail_list_attributes is not None:
            raise self.fail_list_attributes
        return {"attributes": [{"key": key} for key in self.attributes.get(collection_id, set())]}

    def create_string_attribute(
        self, database_id: str, collection_id: str, key: str, size: float, required: bool
    ) -> dict:
        if self.fail_create_attribute is not None:
            raise self.fail_create_attribute
        if key in self.attributes[collection_id]:
            raise _err(409, "attribute_already_exists")
        self.attributes[collection_id].add(key)
        return {"key": key, "size": size, "required": required}

    def create_integer_attribute(
        self, database_id: str, collection_id: str, key: str, required: bool
    ) -> dict:
        if self.fail_create_attribute is not None:
            raise self.fail_create_attribute
        if key in self.attributes[collection_id]:
            raise _err(409, "attribute_already_exists")
        self.attributes[collection_id].add(key)
        return {"key": key, "required": required}

    def list_indexes(self, database_id: str, collection_id: str) -> dict:
        if self.fail_list_indexes is not None:
            raise self.fail_list_indexes
        return {"indexes": [{"key": key} for key in self.indexes.get(collection_id, set())]}

    def create_index(
        self, database_id: str, collection_id: str, key: str, type: object, attributes: list[str]
    ) -> dict:
        if self.fail_create_index is not None:
            raise self.fail_create_index
        if key in self.indexes[collection_id]:
            raise _err(409, "index_already_exists")
        self.indexes[collection_id].add(key)
        return {"key": key, "type": str(type), "attributes": attributes}

    def list_documents(
        self, database_id: str, collection_id: str, queries: list[str] | None = None
    ) -> dict:
        if self.fail_list_documents is not None:
            raise self.fail_list_documents
        if collection_id not in self.collections:
            raise _err(404, "collection_not_found")
        filters, limit, offset = {}, None, 0
        for raw in queries or []:
            parsed = json.loads(raw)
            if parsed["method"] == "equal":
                filters[parsed["attribute"]] = parsed["values"][0]
            elif parsed["method"] == "limit":
                limit = parsed["values"][0]
            elif parsed["method"] == "offset":
                offset = parsed["values"][0]
        matched = [
            doc
            for doc in self.documents[collection_id].values()
            if all(doc.get(key) == value for key, value in filters.items())
        ]
        end = None if limit is None else offset + limit
        return {"documents": matched[offset:end], "total": len(matched)}


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


def test_list_all_documents_paginates_and_applies_sdk_queries() -> None:
    fake = FakeDatabases()
    fake.databases.add(DATABASE_ID)
    fake.collections[PENDENCY_COLLECTION_ID] = {}
    fake.documents[PENDENCY_COLLECTION_ID] = {}
    for index in range(LIST_PAGE_SIZE + 5):
        fake.documents[PENDENCY_COLLECTION_ID][f"doc-{index}"] = {
            "$id": f"doc-{index}",
            "user_id": "user-1" if index % 2 else "user-2",
        }
    from appwrite.query import Query

    result = list_all_documents(
        fake, DATABASE_ID, PENDENCY_COLLECTION_ID, [Query.equal("user_id", "user-1")]
    )
    assert len(result) == (LIST_PAGE_SIZE + 5) // 2  # odd indexes only
    assert all(doc["user_id"] == "user-1" for doc in result)


def test_list_all_documents_raises_on_service_failure_and_missing_collection() -> None:
    fake = FakeDatabases()
    fake.fail_list_documents = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        list_all_documents(fake, DATABASE_ID, PENDENCY_COLLECTION_ID, [])
    fake.fail_list_documents = _err(404, "collection_not_found")
    with pytest.raises(StorageNotProvisioned):
        list_all_documents(fake, DATABASE_ID, PENDENCY_COLLECTION_ID, [])


def test_list_all_documents_budgets_infinite_pages() -> None:
    class AlwaysFull:
        def list_documents(self, **kwargs: object) -> dict:
            return {"documents": [{"$id": f"d{i}"} for i in range(LIST_PAGE_SIZE)], "total": 10**9}

    with pytest.raises(StorageUnavailable):
        list_all_documents(AlwaysFull(), DATABASE_ID, PENDENCY_COLLECTION_ID, [])  # type: ignore[arg-type]


def test_list_all_documents_accepts_model_like_responses() -> None:
    class ModelResponse:
        def to_dict(self) -> dict:
            return {"documents": [{"$id": "d1"}]}

    class OnePage:
        def list_documents(self, **kwargs: object) -> ModelResponse:
            return ModelResponse()

    assert list_all_documents(OnePage(), DATABASE_ID, PENDENCY_COLLECTION_ID, []) == [  # type: ignore[arg-type]
        {"$id": "d1"}
    ]


def test_ensure_creates_database_collections_attributes_and_indexes_idempotently() -> None:
    fake = FakeDatabases()
    summary = ensure_appwrite_storage(fake)
    assert summary["database"] == "created"
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "created"}
    assert summary["collections"][DRAFT_COLLECTION_ID] == {"status": "created"}
    call = fake.create_collection_calls[0]
    assert call["document_security"] is True
    assert call["permissions"] == []
    assert {attr["key"] for attr in call["attributes"]} >= {"user_id", "course_id"}
    assert {idx["key"] for idx in call["indexes"]} >= {"idx_user_id"}

    # Second run is a no-op: everything already exists.
    again = ensure_appwrite_storage(fake)
    assert again["database"] == "exists"
    assert again["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}
    assert len(fake.create_collection_calls) == 2
    assert fake.attributes[PENDENCY_COLLECTION_ID]  # attributes ensured on create path


def test_ensure_backfills_missing_attributes_and_indexes_on_existing_collection() -> None:
    fake = FakeDatabases()
    fake.databases.add(DATABASE_ID)
    fake.collections[PENDENCY_COLLECTION_ID] = {}
    fake.attributes[PENDENCY_COLLECTION_ID] = {"user_id"}
    fake.indexes[PENDENCY_COLLECTION_ID] = {"idx_user_id"}

    summary = ensure_appwrite_storage(
        fake, collections={PENDENCY_COLLECTION_ID: COLLECTION_SPECS[PENDENCY_COLLECTION_ID]}
    )

    assert summary["database"] == "exists"
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    assert fake.attributes[PENDENCY_COLLECTION_ID] == {a["key"] for a in spec["attributes"]}
    assert fake.indexes[PENDENCY_COLLECTION_ID] == {i["key"] for i in spec["indexes"]}
    # integer attribute path (attempt_count in drafts) is exercised via draft spec
    ensure_appwrite_storage(
        fake, collections={DRAFT_COLLECTION_ID: COLLECTION_SPECS[DRAFT_COLLECTION_ID]}
    )
    assert "attempt_count" in fake.attributes[DRAFT_COLLECTION_ID]


def test_ensure_tolerates_409_races_and_classifies_real_failures() -> None:
    fake = FakeDatabases()
    # database get fails with non-404 -> unavailable
    fake.fail_get_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(fake)
    # database created between get and create -> 409 race is fine
    fake.fail_get_db = _err(404, "database_not_found")
    fake.fail_create_db = _err(409, "database_already_exists")
    assert ensure_appwrite_storage(fake)["database"] == "exists"
    fake.fail_create_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(fake)

    fake.fail_get_db = None
    fake.fail_create_db = None
    fake.databases.add(DATABASE_ID)
    # collection get fails with non-404 -> unavailable
    fake.fail_get_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(
            fake, collections={PENDENCY_COLLECTION_ID: COLLECTION_SPECS[PENDENCY_COLLECTION_ID]}
        )
    # collection create fails hard -> unavailable; 409 race falls back to backfill
    fake.fail_get_collection = _err(404, "collection_not_found")
    fake.fail_create_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(
            fake, collections={PENDENCY_COLLECTION_ID: COLLECTION_SPECS[PENDENCY_COLLECTION_ID]}
        )
    fake.fail_create_collection = _err(409, "collection_already_exists")
    fake.collections[PENDENCY_COLLECTION_ID] = {}
    fake.attributes[PENDENCY_COLLECTION_ID] = set()
    fake.indexes[PENDENCY_COLLECTION_ID] = set()
    summary = ensure_appwrite_storage(
        fake, collections={PENDENCY_COLLECTION_ID: COLLECTION_SPECS[PENDENCY_COLLECTION_ID]}
    )
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}


def test_ensure_backfill_classifies_attribute_and_index_failures() -> None:
    fake = FakeDatabases()
    fake.databases.add(DATABASE_ID)
    fake.collections[PENDENCY_COLLECTION_ID] = {}
    fake.attributes[PENDENCY_COLLECTION_ID] = set()
    fake.indexes[PENDENCY_COLLECTION_ID] = set()

    fake.fail_list_attributes = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(
            fake, collections={PENDENCY_COLLECTION_ID: COLLECTION_SPECS[PENDENCY_COLLECTION_ID]}
        )
    fake.fail_list_attributes = None

    # 409 on attribute create is a race, not a failure
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    fake.attributes[PENDENCY_COLLECTION_ID] = {a["key"] for a in spec["attributes"]}
    fake.fail_create_attribute = _err(409, "attribute_already_exists")
    fake.fail_list_indexes = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(fake, collections={PENDENCY_COLLECTION_ID: spec})
    fake.fail_list_indexes = None
    fake.fail_create_attribute = _err(500, "general")
    fake.attributes[PENDENCY_COLLECTION_ID] = set()
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(fake, collections={PENDENCY_COLLECTION_ID: spec})
    fake.fail_create_attribute = None

    spec_attrs = {a["key"] for a in spec["attributes"]}
    fake.attributes[PENDENCY_COLLECTION_ID] = spec_attrs
    fake.fail_list_indexes = None
    fake.indexes[PENDENCY_COLLECTION_ID] = {i["key"] for i in spec["indexes"]}
    fake.fail_create_index = _err(409, "index_already_exists")
    ensure_appwrite_storage(fake, collections={PENDENCY_COLLECTION_ID: spec})
    fake.fail_create_index = _err(500, "general")
    fake.indexes[PENDENCY_COLLECTION_ID] = set()
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(fake, collections={PENDENCY_COLLECTION_ID: spec})


def test_validate_reports_missing_collections_and_failures() -> None:
    fake = FakeDatabases()
    with pytest.raises(StorageNotProvisioned):
        validate_appwrite_storage(fake)
    fake.fail_get_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(fake)
    fake.fail_get_db = None
    fake.databases.add(DATABASE_ID)
    fake.fail_get_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(fake)
    fake.fail_get_collection = None
    fake.collections[PENDENCY_COLLECTION_ID] = {}
    with pytest.raises(StorageNotProvisioned):
        validate_appwrite_storage(fake)
    fake.collections[DRAFT_COLLECTION_ID] = {}
    assert validate_appwrite_storage(fake) == {
        "database": DATABASE_ID,
        "collections": sorted(COLLECTION_SPECS),
    }


def test_ensure_backfills_integer_attributes_and_tolerates_create_races() -> None:
    fake = FakeDatabases()
    fake.databases.add(DATABASE_ID)
    # both collections exist but are empty of attributes/indexes
    for collection_id in COLLECTION_SPECS:
        fake.collections[collection_id] = {}
        fake.attributes[collection_id] = set()
        fake.indexes[collection_id] = set()

    # 409 races on attribute/index creation are tolerated (concurrent provisioning)
    fake.fail_create_attribute = _err(409, "attribute_already_exists")
    fake.fail_create_index = _err(409, "index_already_exists")
    summary = ensure_appwrite_storage(fake)
    assert summary["database"] == "exists"
    assert all(value == {"status": "exists"} for value in summary["collections"].values())

    # real backfill creates string AND integer attributes (attempt_count)
    fake.fail_create_attribute = None
    fake.fail_create_index = None
    ensure_appwrite_storage(fake)
    for collection_id, spec in COLLECTION_SPECS.items():
        assert fake.attributes[collection_id] == {a["key"] for a in spec["attributes"]}
        assert fake.indexes[collection_id] == {i["key"] for i in spec["indexes"]}
    assert "attempt_count" in fake.attributes[DRAFT_COLLECTION_ID]
