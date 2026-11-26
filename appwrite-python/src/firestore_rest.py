"""Firestore REST access that remains constrained by each user's Security Rules."""

import json
import re
from collections.abc import Callable, Mapping
from os import environ
from time import perf_counter
from typing import Any, cast
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

MAX_PAYLOAD_BYTES = 1_048_576
MAX_TOKEN_LENGTH = 16_384
PRODUCTION_BASE_URL = "https://firestore.googleapis.com/v1"
Transport = Callable[[Request, float], tuple[int, bytes]]
Telemetry = Callable[[str, Mapping[str, object]], None]


class FirestoreRestError(Exception):
    """A sanitized failure at the Firestore REST boundary."""


class FirestoreAccessDenied(FirestoreRestError):
    """Firestore Security Rules rejected the current user."""


class FirestoreConflict(FirestoreRestError):
    """A concurrent writer changed the document before the conditional write."""


class FirestoreNotFound(FirestoreRestError):
    """The requested Firestore document does not exist."""


class FirestoreRequestRejected(FirestoreRestError):
    """Firestore rejected a malformed request or credential."""


class FirestoreRateLimited(FirestoreRestError):
    """Firestore refused the request with HTTP 429, preserving its error code."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 429,
        error_code: str = "RESOURCE_EXHAUSTED",
        retry_after: float | None = None,
    ) -> None:
        """Keep the refusal status, machine error code, and optional retry hint."""
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after


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
        telemetry: Telemetry | None = None,
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
        self._telemetry = telemetry
        self.base_url = _base_url()

    def get_user_document(self, *segments: str) -> dict[str, Any]:
        """Read a document owned by the verified user."""

        return self._request("GET", segments)

    def patch_user_document(
        self,
        *segments: str,
        fields: Mapping[str, Any],
        update_mask: tuple[str, ...] | None = None,
        expected_update_time: str | None = None,
        create_only: bool = False,
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
        if expected_update_time is not None or create_only:
            query = query or []
            query.append(
                ("currentDocument.updateTime", expected_update_time)
                if expected_update_time
                else ("currentDocument.exists", "false")
            )
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

    def batch_get_user_documents(
        self, paths: list[tuple[str, ...]]
    ) -> dict[tuple[str, ...], dict[str, Any] | None]:
        """Read up to 100 known documents with one Firestore batch request.

        Firestore's ``batchGet`` response is streamed as one JSON object per
        document, so the transport keeps the response bounded and the parser
        below validates every requested name before returning it.  Missing
        documents are represented by ``None`` instead of raising, matching the
        useful behavior of a collection listing for repositories that reconcile
        optional ``current`` documents.
        """

        if (
            not paths
            or len(paths) > 100
            or len({tuple(path) for path in paths}) != len(paths)
            or any(len(path) == 0 or len(path) % 2 != 0 for path in paths)
        ):
            raise ValueError("invalid Firestore batch get")
        names = [self._document_name(tuple(path)) for path in paths]
        body = json.dumps({"documents": names}, separators=(",", ":")).encode()
        if len(body) > MAX_PAYLOAD_BYTES:
            raise ValueError("Firestore payload is too large")
        project = quote(self._project_id, safe="")
        url = f"{self.base_url}/projects/{project}/databases/(default)/documents:batchGet"
        raw = self._send("POST", url, body, streamed_json=True)
        if not isinstance(raw, list):
            raise FirestoreUnavailable("Firestore is unavailable")
        requested = {name: tuple(path) for name, path in zip(names, paths, strict=True)}
        result: dict[tuple[str, ...], dict[str, Any] | None] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise FirestoreUnavailable("Firestore is unavailable")
            found = item.get("found")
            missing = item.get("missing")
            if isinstance(found, dict) and missing is None:
                name = found.get("name")
                if not isinstance(name, str) or name not in requested:
                    raise FirestoreUnavailable("Firestore is unavailable")
                path = requested[name]
                if path in result:
                    raise FirestoreUnavailable("Firestore is unavailable")
                result[path] = found
            elif isinstance(missing, str) and found is None:
                if missing not in requested:
                    raise FirestoreUnavailable("Firestore is unavailable")
                path = requested[missing]
                if path in result:
                    raise FirestoreUnavailable("Firestore is unavailable")
                result[path] = None
            else:
                # A transaction header or malformed union is not a usable
                # document result for this non-transactional request.
                raise FirestoreUnavailable("Firestore is unavailable")
        if set(result) != set(tuple(path) for path in paths):
            raise FirestoreUnavailable("Firestore is unavailable")
        return result

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
            body = json.dumps(
                {"writes": writes}, ensure_ascii=False, separators=(",", ":")
            ).encode()
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
        response = self._send(method, url, body, allow_empty=allow_empty)
        if not isinstance(response, dict):
            raise FirestoreUnavailable("Firestore is unavailable")
        return response

    def _send(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        *,
        allow_empty: bool = False,
        streamed_json: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        started = perf_counter()
        status: int | None = None
        response_body = b""
        outcome = "failed"
        headers = {"Authorization": f"Bearer {self._id_token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)

        try:
            try:
                status, response_body = self._transport(request, self._timeout_seconds)
            except OSError:
                raise FirestoreUnavailable("Firestore is unavailable") from None

            if status in (401, 403):
                raise FirestoreAccessDenied("Firestore denied the request")
            if status == 404:
                outcome = "not_found"
                raise FirestoreNotFound("Firestore document was not found")
            if status in (409, 412):
                raise FirestoreConflict("Firestore document changed concurrently")
            if status == 400:
                raise FirestoreRequestRejected("Firestore rejected the request")
            if status == 429:
                outcome = "rate_limited"
                raise FirestoreRateLimited(
                    "Firestore rate limit exceeded",
                    status_code=429,
                    error_code=_error_code(response_body),
                )
            if not 200 <= status < 300 or len(response_body) > MAX_PAYLOAD_BYTES:
                raise FirestoreUnavailable("Firestore is unavailable")
            if not response_body and allow_empty:
                outcome = "succeeded"
                return {}
            try:
                decoded: object
                if streamed_json:
                    decoded = _decode_streamed_json(response_body)
                else:
                    decoded = json.loads(response_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise FirestoreUnavailable("Firestore is unavailable") from None
            if streamed_json:
                if not isinstance(decoded, list) or any(
                    not isinstance(item, dict) for item in decoded
                ):
                    raise FirestoreUnavailable("Firestore is unavailable")
            elif not isinstance(decoded, dict):
                raise FirestoreUnavailable("Firestore is unavailable")
            outcome = "succeeded"
            return cast(dict[str, Any] | list[dict[str, Any]], decoded)
        finally:
            self._emit_telemetry(
                "firestore_request_completed",
                {
                    "duration_ms": round((perf_counter() - started) * 1_000, 3),
                    "kind": "read"
                    if method == "GET" or url.endswith(":batchGet")
                    else "write",
                    "method": method,
                    "outcome": outcome,
                    "status_class": f"{status // 100}xx" if status is not None else "network",
                    "status_code": status,
                    # Keep the dependency trace useful without leaking the
                    # verified uid, document contents, or bearer token. The
                    # request body size is enough to spot oversized writes;
                    # response size helps separate a slow read from parsing.
                    "resource": _telemetry_resource(url),
                    "request_bytes": len(body or b""),
                    "response_bytes": len(response_body),
                    "attempt": 1,
                    "retry_count": 0,
                },
            )

    def _emit_telemetry(self, event: str, fields: Mapping[str, object]) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry(event, fields)
        except Exception:
            return

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


def _error_code(response_body: bytes) -> str:
    """Extract the machine error code (for example RESOURCE_EXHAUSTED) from a 429 body."""
    try:
        decoded = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "RESOURCE_EXHAUSTED"
    if not isinstance(decoded, dict):
        return "RESOURCE_EXHAUSTED"
    error = decoded.get("error")
    if isinstance(error, dict) and isinstance(error.get("status"), str) and error["status"]:
        return cast(str, error["status"])
    return "RESOURCE_EXHAUSTED"


def _decode_streamed_json(response_body: bytes) -> list[dict[str, Any]]:
    """Decode Firestore's array or newline/concatenated JSON batch response.

    The REST endpoint normally streams one object per line, but compatible
    Firestore transports (including the official Firebase client) can return
    the same batch as one JSON array.  Accept both wire formats while keeping
    the strict object-only validation used by the batch reconciliation code.
    """

    text = response_body.decode("utf-8")
    first_non_whitespace = next(
        (index for index, char in enumerate(text) if not char.isspace()), None
    )
    if first_non_whitespace is None:
        return []
    if text[first_non_whitespace] == "[":
        decoded = json.loads(text)
        if not isinstance(decoded, list) or any(
            not isinstance(item, dict) for item in decoded
        ):
            raise json.JSONDecodeError(
                "Firestore batch items must be objects", text, first_non_whitespace
            )
        return decoded

    decoder = json.JSONDecoder()
    values: list[dict[str, Any]] = []
    offset = 0
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset >= len(text):
            break
        value, offset = decoder.raw_decode(text, offset)
        if not isinstance(value, dict):
            raise json.JSONDecodeError("Firestore batch item must be an object", text, offset)
        values.append(value)
    return values


def _telemetry_resource(url: str) -> str:
    """Return a bounded Firestore path with owner and document IDs redacted."""

    path = urlsplit(url).path
    marker = "/documents/users/"
    if marker not in path:
        return path or "/"
    prefix, remainder = path.split(marker, 1)
    segments = remainder.split("/")
    segments[0] = "{user}"
    # Firestore alternates collection/document segments. Keep collection names
    # so the trace remains actionable, but never emit any document identifier.
    for index in range(2, len(segments), 2):
        segments[index] = "{doc}"
    return prefix + marker + "/".join(segments)


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
