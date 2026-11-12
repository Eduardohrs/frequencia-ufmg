"""Appwrite storage contract: error taxonomy, paginated queries, provisioning.

The function persists schedule pendencies and registration drafts in the
``frequencia_ufmg`` database. Server SDK API keys ignore document permissions,
so every document stores its ``user_id`` owner and the repositories validate it
before acting. List queries must use SDK ``Query`` objects (serialized as
JSON), and backend failures are propagated instead of being hidden as empty
lists. ``ensure_appwrite_storage`` provisions the database/collections with
the attributes and indexes the repositories require, idempotently, and
``validate_appwrite_storage`` fails loudly when they are missing.
"""

from collections.abc import Mapping
from typing import Any, Protocol, cast

from appwrite.enums.databases_index_type import DatabasesIndexType
from appwrite.exception import AppwriteException
from appwrite.query import Query

DATABASE_ID = "frequencia_ufmg"
PENDENCY_COLLECTION_ID = "schedule_pendencies"
DRAFT_COLLECTION_ID = "registration_drafts"

LIST_PAGE_SIZE = 100
MAX_LIST_PAGES = 1000

DOCUMENT_NOT_FOUND_TYPE = "document_not_found"
COLLECTION_NOT_FOUND_TYPE = "collection_not_found"
DATABASE_NOT_FOUND_TYPE = "database_not_found"


class StorageNotFound(Exception):
    """The requested document does not exist or is not owned by the caller."""


class StorageNotProvisioned(Exception):
    """The database or collection required by the service is missing."""


class StorageUnavailable(Exception):
    """The storage backend failed; absence of data must not be assumed."""


class _Databases(Protocol):
    def get(self, database_id: str) -> Any: ...

    def create(self, database_id: str, name: str) -> Any: ...

    def get_collection(self, database_id: str, collection_id: str) -> Any: ...

    def create_collection(
        self, database_id: str, collection_id: str, name: str, **kwargs: Any
    ) -> Any: ...

    def list_attributes(self, database_id: str, collection_id: str) -> Any: ...

    def create_string_attribute(
        self, database_id: str, collection_id: str, key: str, size: float, required: bool
    ) -> Any: ...

    def create_integer_attribute(
        self, database_id: str, collection_id: str, key: str, required: bool
    ) -> Any: ...

    def list_indexes(self, database_id: str, collection_id: str) -> Any: ...

    def create_index(
        self,
        database_id: str,
        collection_id: str,
        key: str,
        type: Any,
        attributes: list[str],
    ) -> Any: ...

    def list_documents(
        self, database_id: str, collection_id: str, queries: list[str] | None = None
    ) -> Any: ...


def classify_error(error: AppwriteException, *, operation: str, document_level: bool) -> Exception:
    """Map one Appwrite failure to the storage error taxonomy."""
    code = getattr(error, "code", 0)
    error_type = getattr(error, "type", None)
    if code == 404:
        if error_type in (COLLECTION_NOT_FOUND_TYPE, DATABASE_NOT_FOUND_TYPE):
            return StorageNotProvisioned(f"{operation}: {error_type}")
        if document_level and error_type in (None, DOCUMENT_NOT_FOUND_TYPE):
            return StorageNotFound(f"{operation}: document_not_found")
        return StorageNotProvisioned(f"{operation}: resource_not_found ({error_type})")
    return StorageUnavailable(f"{operation}: appwrite error {code} ({error_type})")


def list_all_documents(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    queries: list[str],
) -> list[dict[str, Any]]:
    """List every matching document using SDK queries with offset pagination."""
    documents: list[dict[str, Any]] = []
    offset = 0
    for _ in range(MAX_LIST_PAGES):
        page_queries = [*queries, Query.limit(LIST_PAGE_SIZE), Query.offset(offset)]
        try:
            response = databases.list_documents(
                database_id=database_id,
                collection_id=collection_id,
                queries=page_queries,
            )
        except AppwriteException as error:
            raise classify_error(error, operation="list_documents", document_level=False) from None
        page = list(_as_mapping(response).get("documents", []))
        documents.extend(page)
        if len(page) < LIST_PAGE_SIZE:
            return documents
        offset += LIST_PAGE_SIZE
    raise StorageUnavailable("list_documents exceeded the pagination budget")


def _as_mapping(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    return cast(Mapping[str, Any], response.to_dict())


def _string_attribute(key: str, size: float, required: bool) -> dict[str, Any]:
    return {"key": key, "type": "string", "size": size, "required": required}


PENDENCY_COLLECTION_SPEC: dict[str, Any] = {
    "name": "Schedule pendencies",
    "attributes": [
        _string_attribute("user_id", 128, True),
        _string_attribute("course_id", 128, True),
        _string_attribute("course_code", 64, True),
        _string_attribute("course_name", 512, True),
        _string_attribute("current_schedule", 1024, True),
        _string_attribute("new_schedule", 1024, True),
        _string_attribute("reason", 256, True),
        _string_attribute("decision", 64, False),
        _string_attribute("status", 32, True),
        _string_attribute("payload", 100_000, False),
        _string_attribute("created_at", 64, True),
        _string_attribute("updated_at", 64, True),
    ],
    "indexes": [
        {"key": "idx_user_id", "type": "key", "attributes": ["user_id"]},
        {"key": "idx_user_course", "type": "key", "attributes": ["user_id", "course_id"]},
    ],
}

DRAFT_COLLECTION_SPEC: dict[str, Any] = {
    "name": "Registration drafts",
    "attributes": [
        _string_attribute("user_id", 128, True),
        _string_attribute("course_id", 128, True),
        _string_attribute("course_code", 64, True),
        _string_attribute("session_id", 256, True),
        _string_attribute("form_data", 100_000, True),
        _string_attribute("last_error", 512, False),
        {"key": "attempt_count", "type": "integer", "required": True},
        _string_attribute("created_at", 64, True),
        _string_attribute("updated_at", 64, True),
    ],
    "indexes": [
        {"key": "idx_user_id", "type": "key", "attributes": ["user_id"]},
        {"key": "idx_user_course", "type": "key", "attributes": ["user_id", "course_id"]},
        {"key": "idx_user_session", "type": "key", "attributes": ["user_id", "session_id"]},
    ],
}

COLLECTION_SPECS: dict[str, dict[str, Any]] = {
    PENDENCY_COLLECTION_ID: PENDENCY_COLLECTION_SPEC,
    DRAFT_COLLECTION_ID: DRAFT_COLLECTION_SPEC,
}


def ensure_appwrite_storage(
    databases: _Databases,
    database_id: str = DATABASE_ID,
    collections: Mapping[str, Mapping[str, Any]] = COLLECTION_SPECS,
) -> dict[str, Any]:
    """Idempotently create the database, collections, attributes, and indexes."""
    return {
        "database": _ensure_database(databases, database_id),
        "collections": {
            collection_id: _ensure_collection(databases, database_id, collection_id, spec)
            for collection_id, spec in collections.items()
        },
    }


def validate_appwrite_storage(
    databases: _Databases,
    database_id: str = DATABASE_ID,
    collections: Mapping[str, Mapping[str, Any]] = COLLECTION_SPECS,
) -> dict[str, Any]:
    """Fail loudly when the database or any required collection is missing."""
    try:
        databases.get(database_id)
    except AppwriteException as error:
        raise classify_error(error, operation="get_database", document_level=False) from None
    missing: list[str] = []
    for collection_id in collections:
        try:
            databases.get_collection(database_id, collection_id)
        except AppwriteException as error:
            if error.code == 404:
                missing.append(collection_id)
            else:
                raise classify_error(
                    error, operation="get_collection", document_level=False
                ) from None
    if missing:
        raise StorageNotProvisioned(f"missing collections: {', '.join(sorted(missing))}")
    return {"database": database_id, "collections": sorted(collections)}


def _ensure_database(databases: _Databases, database_id: str) -> str:
    try:
        databases.get(database_id)
        return "exists"
    except AppwriteException as error:
        if error.code != 404:
            raise classify_error(error, operation="get_database", document_level=False) from None
    try:
        databases.create(database_id, database_id)
        return "created"
    except AppwriteException as error:
        if error.code == 409:
            return "exists"
        raise classify_error(error, operation="create_database", document_level=False) from None


def _ensure_collection(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        databases.get_collection(database_id, collection_id)
    except AppwriteException as error:
        if error.code != 404:
            raise classify_error(error, operation="get_collection", document_level=False) from None
        try:
            databases.create_collection(
                database_id,
                collection_id,
                str(spec["name"]),
                permissions=[],
                document_security=True,
                attributes=list(spec["attributes"]),
                indexes=list(spec["indexes"]),
            )
            return {"status": "created"}
        except AppwriteException as create_error:
            if create_error.code != 409:
                raise classify_error(
                    create_error, operation="create_collection", document_level=False
                ) from None
    _ensure_attributes(databases, database_id, collection_id, spec)
    _ensure_indexes(databases, database_id, collection_id, spec)
    return {"status": "exists"}


def _ensure_attributes(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    spec: Mapping[str, Any],
) -> None:
    try:
        response = databases.list_attributes(database_id, collection_id)
    except AppwriteException as error:
        raise classify_error(error, operation="list_attributes", document_level=False) from None
    existing = {str(item.get("key")) for item in _as_mapping(response).get("attributes", [])}
    for attribute in spec["attributes"]:
        key = str(attribute["key"])
        if key in existing:
            continue
        try:
            if attribute["type"] == "string":
                databases.create_string_attribute(
                    database_id,
                    collection_id,
                    key,
                    float(attribute["size"]),
                    bool(attribute["required"]),
                )
            else:
                databases.create_integer_attribute(
                    database_id,
                    collection_id,
                    key,
                    bool(attribute["required"]),
                )
        except AppwriteException as error:
            if error.code != 409:
                raise classify_error(
                    error, operation="create_attribute", document_level=False
                ) from None


def _ensure_indexes(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    spec: Mapping[str, Any],
) -> None:
    try:
        response = databases.list_indexes(database_id, collection_id)
    except AppwriteException as error:
        raise classify_error(error, operation="list_indexes", document_level=False) from None
    existing = {str(item.get("key")) for item in _as_mapping(response).get("indexes", [])}
    for index in spec["indexes"]:
        key = str(index["key"])
        if key in existing:
            continue
        try:
            databases.create_index(
                database_id,
                collection_id,
                key,
                DatabasesIndexType.KEY,
                [str(name) for name in index["attributes"]],
            )
        except AppwriteException as error:
            if error.code != 409:
                raise classify_error(
                    error, operation="create_index", document_level=False
                ) from None
