"""Appwrite storage contract: error taxonomy, paginated queries, ownership.

The function persists schedule pendencies and registration drafts in the
database configured by ``SECURITY_DATABASE_ID`` — the same database that
already holds the security/session tables. Repositories receive the database
id explicitly from the caller, so a missing configuration fails loudly
instead of silently selecting a nonexistent database.

Server SDK API keys ignore document permissions, so every document stores
its ``user_id`` owner and the repositories validate it before acting. List
queries must use SDK ``Query`` objects (serialized as JSON), and backend
failures are propagated instead of being hidden as empty lists.

The versioned schema of the two collections and the optional, operator-run
provisioner live OUTSIDE the runtime bundle, in ``storage_schema.py`` and
``setup_storage.py`` at the ``appwrite-python`` package root; production
deploy never creates schema.
"""

from typing import Any, Protocol

from appwrite.exception import AppwriteException
from appwrite.models import Document
from appwrite.query import Query

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
            f"{operation}: API key rejected (appwrite error {code} ({error_type}))"
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
