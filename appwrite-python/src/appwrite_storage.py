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

import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from appwrite.enums.databases_index_type import DatabasesIndexType
from appwrite.exception import AppwriteException
from appwrite.models import Document
from appwrite.query import Query

DATABASE_ID = "frequencia_ufmg"
PENDENCY_COLLECTION_ID = "schedule_pendencies"
DRAFT_COLLECTION_ID = "registration_drafts"

LIST_PAGE_SIZE = 100
MAX_LIST_PAGES = 1000

READY_POLL_INTERVAL_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 300.0
FAILED_RESOURCE_STATUSES = frozenset({"failed", "stuck"})
PROVISIONING_KEY_SCOPES = (
    "tablesdb.write (or legacy databases.write, collections.write, "
    "attributes.write, indexes.write)"
)

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
    if code in (401, 403):
        return StorageUnavailable(
            f"{operation}: API key rejected (appwrite error {code} ({error_type})); "
            f"provisioning needs a project key with schema-write scopes: "
            f"{PROVISIONING_KEY_SCOPES}"
        )
    return StorageUnavailable(f"{operation}: appwrite error {code} ({error_type})")


def normalize_document(document: Document[dict[str, Any]]) -> dict[str, Any]:
    """Flatten one SDK 27.x ``Document`` model into a plain dict.

    ``Databases.get_document``/``create_document``/``update_document`` return
    ``Document.with_data(http_json, dict)`` whose ``to_dict()`` nests the
    business fields under ``data``. This merges them back next to the
    ``$``-prefixed metadata (``$id``, ``$permissions``, ``$createdAt``, ...).
    """
    as_dict = dict(document.to_dict())
    payload = as_dict.pop("data", {})
    as_dict.update(payload)
    return as_dict


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
        page = [normalize_document(doc) for doc in response.documents]
        documents.extend(page)
        if len(page) < LIST_PAGE_SIZE:
            return documents
        offset += LIST_PAGE_SIZE
    raise StorageUnavailable("list_documents exceeded the pagination budget")


def _as_mapping(response: Any) -> dict[str, Any]:
    """Flatten one real SDK response model (``AttributeList``, ``IndexList``, ...)."""
    return dict(response.to_dict())


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
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = READY_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Idempotently create the database, collections, attributes, and indexes.

    Waits (bounded by ``timeout_seconds``) for attributes to reach ``available``
    before creating indexes and for indexes to be ``available`` before returning.
    """
    return {
        "database": _ensure_database(databases, database_id),
        "collections": {
            collection_id: _ensure_collection(
                databases,
                database_id,
                collection_id,
                spec,
                sleep=sleep,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )
            for collection_id, spec in collections.items()
        },
    }


def validate_appwrite_storage(
    databases: _Databases,
    database_id: str = DATABASE_ID,
    collections: Mapping[str, Mapping[str, Any]] = COLLECTION_SPECS,
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = READY_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fail loudly until the database, collections, attributes, and indexes are ready.

    Attributes and indexes are provisioned asynchronously: existence of a key is
    not enough, so each spec entry must reach status ``available`` (bounded wait)
    before the storage is considered usable by a deployment.
    """
    try:
        databases.get(database_id)
    except AppwriteException as error:
        raise classify_error(error, operation="get_database", document_level=False) from None
    missing: list[str] = []
    for collection_id, spec in collections.items():
        try:
            databases.get_collection(database_id, collection_id)
        except AppwriteException as error:
            if error.code == 404:
                missing.append(collection_id)
                continue
            raise classify_error(
                error, operation="get_collection", document_level=False
            ) from None
        try:
            wait_for_spec_ready(
                databases,
                database_id,
                collection_id,
                spec,
                sleep=sleep,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            )
        except StorageNotProvisioned as error:
            missing.append(f"{collection_id}: {error}")
    if missing:
        raise StorageNotProvisioned(f"missing storage spec: {', '.join(sorted(missing))}")
    return {"database": database_id, "collections": sorted(collections)}


def _spec_resource_status(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    spec: Mapping[str, Any],
) -> dict[str, tuple[str, str]]:
    """Map each spec entry to its live ``(status, error)``; missing entries are empty."""
    try:
        attributes = databases.list_attributes(database_id, collection_id)
    except AppwriteException as error:
        raise classify_error(error, operation="list_attributes", document_level=False) from None
    try:
        indexes = databases.list_indexes(database_id, collection_id)
    except AppwriteException as error:
        raise classify_error(error, operation="list_indexes", document_level=False) from None
    live: dict[str, tuple[str, str]] = {}
    for item in _as_mapping(attributes).get("attributes", []):
        live[f"attribute {item.get('key')}"] = (
            str(item.get("status", "")),
            str(item.get("error", "")),
        )
    for item in _as_mapping(indexes).get("indexes", []):
        live[f"index {item.get('key')}"] = (
            str(item.get("status", "")),
            str(item.get("error", "")),
        )
    entries: dict[str, tuple[str, str]] = {}
    for attribute in spec["attributes"]:
        key = str(attribute["key"])
        entries[f"attribute '{key}'"] = live.get(f"attribute {key}", ("", ""))
    for index in spec["indexes"]:
        key = str(index["key"])
        entries[f"index '{key}'"] = live.get(f"index {key}", ("", ""))
    return entries


def _not_ready(entries: Mapping[str, tuple[str, str]]) -> list[str]:
    """Describe spec entries that are not ``available``; raise on failed/stuck."""
    not_ready: list[str] = []
    for name, (status, error) in sorted(entries.items()):
        detail = f" error={error}" if error else ""
        if status in FAILED_RESOURCE_STATUSES:
            raise StorageNotProvisioned(f"storage resource {name} status={status}{detail}")
        if status != "available":
            not_ready.append(f"{name} status={status or 'missing'}{detail}")
    return not_ready


def wait_for_spec_ready(
    databases: _Databases,
    database_id: str,
    collection_id: str,
    spec: Mapping[str, Any],
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = READY_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> None:
    """Poll until every spec attribute/index exists with status ``available``.

    Bounded by ``timeout_seconds``: on timeout raises ``StorageNotProvisioned``
    listing each not-ready resource with its status/error. ``failed``/``stuck``
    resources fail immediately.
    """
    max_attempts = max(1, round(timeout_seconds / poll_interval_seconds))
    not_ready: list[str] = []
    for attempt in range(max_attempts):
        not_ready = _not_ready(_spec_resource_status(databases, database_id, collection_id, spec))
        if not not_ready:
            return
        if attempt < max_attempts - 1:
            sleep(poll_interval_seconds)
    raise StorageNotProvisioned(
        f"storage spec not ready within {timeout_seconds}s: {'; '.join(not_ready)}"
    )


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
    *,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = READY_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = READY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    status = "exists"
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
            status = "created"
        except AppwriteException as create_error:
            if create_error.code != 409:
                raise classify_error(
                    create_error, operation="create_collection", document_level=False
                ) from None
    _ensure_attributes(databases, database_id, collection_id, spec)
    # Attributes/indexes are provisioned asynchronously; indexes over attributes
    # that are still "processing" fail, so wait for readiness before indexing.
    wait_for_spec_ready(
        databases,
        database_id,
        collection_id,
        {"attributes": spec["attributes"], "indexes": []},
        sleep=sleep,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    _ensure_indexes(databases, database_id, collection_id, spec)
    wait_for_spec_ready(
        databases,
        database_id,
        collection_id,
        spec,
        sleep=sleep,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    return {"status": status}


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
