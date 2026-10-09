"""Firestore REST access that remains constrained by each user's Security Rules."""

import json
import re
from collections.abc import Callable, Mapping
from os import environ
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

MAX_PAYLOAD_BYTES = 1_048_576
MAX_TOKEN_LENGTH = 16_384
PRODUCTION_BASE_URL = "https://firestore.googleapis.com/v1"
Transport = Callable[[Request, float], tuple[int, bytes]]


class FirestoreRestError(Exception):
    """A sanitized failure at the Firestore REST boundary."""


class FirestoreAccessDenied(FirestoreRestError):
    """Firestore Security Rules rejected the current user."""


class FirestoreNotFound(FirestoreRestError):
    """The requested Firestore document does not exist."""


class FirestoreRequestRejected(FirestoreRestError):
    """Firestore rejected a malformed request or credential."""


class FirestoreUnavailable(FirestoreRestError):
    """Firestore could not provide a usable response."""


class FirestoreRestClient:
    """Read and write only below ``users/{verified uid}`` with a Firebase ID token."""

    def __init__(
        self,
        project_id: str,
        user_id: str,
        id_token: str,
        *,
        timeout_seconds: float = 10,
        transport: Transport | None = None,
    ) -> None:
        self._project_id = _segment(project_id, "project_id")
        self._user_id = _segment(user_id, "user_id")
        if (
            not id_token
            or len(id_token) > MAX_TOKEN_LENGTH
            or any(character.isspace() for character in id_token)
        ):
            raise ValueError("invalid Firebase ID token")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("invalid Firestore timeout")
        self._id_token = id_token
        self._timeout_seconds = timeout_seconds
        self._transport = transport or _urlopen_transport
        self.base_url = _base_url()

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        """Read a document owned by the verified user."""

        return self._request("GET", segments)

    def patch_user_document(
        self,
        *segments: str,
        fields: Mapping[str, Any],
        update_mask: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Create or replace fields on a document owned by the verified user."""

        try:
            body = json.dumps(
                {"fields": fields},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError):
            raise ValueError("Firestore fields must be JSON serializable") from None
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ValueError("Firestore payload is too large")
        query = None
        if update_mask is not None:
            if (
                not update_mask
                or len(set(update_mask)) != len(update_mask)
                or set(update_mask) != set(fields)
                or any(
                    re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) is None for field in update_mask
                )
            ):
                raise ValueError("invalid Firestore update mask")
            query = [("updateMask.fieldPaths", field) for field in update_mask]
        return self._request("PATCH", segments, body, query=query)

    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]:
        """List at most 500 documents below a user-owned collection."""

        documents: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query = {"pageSize": "100"}
            if page_token is not None:
                query["pageToken"] = page_token
            page = self._request("GET", segments, query=query, collection=True)
            values = page.get("documents", [])
            if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
                raise FirestoreUnavailable("Firestore is unavailable")
            documents.extend(values)
            next_token = page.get("nextPageToken")
            if next_token is None:
                return documents
            if not isinstance(next_token, str) or not next_token or len(documents) >= 500:
                raise FirestoreUnavailable("Firestore is unavailable")
            page_token = next_token

    def delete_user_document(self, *segments: str) -> None:
        """Delete a document owned by the verified user."""

        self._request("DELETE", segments, allow_empty=True)

    def delete_user_documents(self, paths: list[tuple[str, ...]]) -> None:
        """Delete a bounded set of user documents in one atomic commit."""

        self.commit_user_documents(updates=[], deletes=paths)

    def commit_user_documents(
        self,
        *,
        updates: list[tuple[tuple[str, ...], Mapping[str, Any]]],
        deletes: list[tuple[str, ...]],
    ) -> None:
        """Atomically replace typed fields and delete user-owned documents."""

        if not updates and not deletes or len(updates) + len(deletes) > 500:
            raise ValueError("Firestore commit batch is invalid")
        writes: list[dict[str, Any]] = []
        for path, fields in updates:
            writes.append(
                {
                    "update": {
                        "name": self._document_name(path),
                        "fields": fields,
                    }
                }
            )
        writes.extend({"delete": self._document_name(path)} for path in deletes)
        try:
            body = json.dumps({"writes": writes}, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ValueError("Firestore fields must be JSON serializable") from None
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ValueError("Firestore payload is too large")
        project = quote(self._project_id, safe="")
        url = f"{self.base_url}/projects/{project}/databases/(default)/documents:commit"
        self._send("POST", url, body)

    def _request(
        self,
        method: str,
        segments: tuple[str, ...],
        body: bytes | None = None,
        *,
        query: Mapping[str, str] | list[tuple[str, str]] | None = None,
        collection: bool = False,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        url = self._resource_url(segments, collection=collection)
        if query:
            url = f"{url}?{urlencode(query)}"
        return self._send(method, url, body, allow_empty=allow_empty)

    def _send(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        *,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._id_token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)

        try:
            status, response_body = self._transport(request, self._timeout_seconds)
        except OSError:
            raise FirestoreUnavailable("Firestore is unavailable") from None

        if status in (401, 403):
            raise FirestoreAccessDenied("Firestore denied the request")
        if status == 404:
            raise FirestoreNotFound("Firestore document was not found")
        if status == 400:
            raise FirestoreRequestRejected("Firestore rejected the request")
        if not 200 <= status < 300 or len(response_body) > MAX_PAYLOAD_BYTES:
            raise FirestoreUnavailable("Firestore is unavailable")
        if not response_body and allow_empty:
            return {}
        try:
            decoded = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FirestoreUnavailable("Firestore is unavailable") from None
        if not isinstance(decoded, dict):
            raise FirestoreUnavailable("Firestore is unavailable")
        return decoded

    def _resource_url(self, segments: tuple[str, ...], *, collection: bool) -> str:
        expected_remainder = 1 if collection else 0
        if not segments or len(segments) % 2 != expected_remainder:
            kind = "collection" if collection else "document"
            raise ValueError(f"Firestore {kind} path is invalid")
        return f"{self.base_url}/{self._resource_name(segments)}"

    def _document_name(self, segments: tuple[str, ...]) -> str:
        if not segments or len(segments) % 2 != 0:
            raise ValueError("Firestore document path is invalid")
        return self._resource_name(segments)

    def _resource_name(self, segments: tuple[str, ...]) -> str:
        safe_segments = [
            quote(_segment(segment, "document path segment"), safe="") for segment in segments
        ]
        path = "/".join(("users", quote(self._user_id, safe=""), *safe_segments))
        project = quote(self._project_id, safe="")
        return f"projects/{project}/databases/(default)/documents/{path}"


def _segment(value: str, field: str) -> str:
    if not value or len(value) > 128 or value.strip() != value or "/" in value or "\\" in value:
        raise ValueError(f"invalid {field}")
    return value


def _base_url() -> str:
    emulator_host = environ.get("FIRESTORE_EMULATOR_HOST")
    if not emulator_host:
        return PRODUCTION_BASE_URL
    if not re.fullmatch(r"(?:127\.0\.0\.1|localhost):[1-9][0-9]{0,4}", emulator_host):
        raise ValueError("invalid Firestore emulator host")
    return f"http://{emulator_host}/v1"


def _urlopen_transport(request: Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed allowlisted URL
            return response.status, response.read(MAX_PAYLOAD_BYTES + 1)
    except HTTPError as error:
        return error.code, error.read(MAX_PAYLOAD_BYTES + 1)
