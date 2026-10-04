import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

import firestore_rest as firestore_module
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreRestClient,
    FirestoreUnavailable,
)


def test_get_user_document_uses_the_users_token_and_path() -> None:
    calls: list[tuple[Any, float]] = []

    def transport(request: Any, timeout: float) -> tuple[int, bytes]:
        calls.append((request, timeout))
        return 200, b'{"fields":{"name":{"stringValue":"POO"}}}'

    client = FirestoreRestClient(
        project_id="frequencia-ufmg-eduardo",
        user_id="firebase-user",
        id_token="signed-id-token",
        transport=transport,
    )

    document = client.get_user_document("courses", "dcc203")

    request, timeout = calls[0]
    assert request.full_url == (
        "https://firestore.googleapis.com/v1/projects/frequencia-ufmg-eduardo/"
        "databases/(default)/documents/users/firebase-user/courses/dcc203"
    )
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer signed-id-token"
    assert request.data is None
    assert timeout == 10
    assert document == {"fields": {"name": {"stringValue": "POO"}}}


def test_patch_user_document_sends_only_firestore_fields() -> None:
    calls: list[Any] = []

    def transport(request: Any, _timeout: float) -> tuple[int, bytes]:
        calls.append(request)
        return 200, request.data

    client = FirestoreRestClient("project", "user", "token", transport=transport)
    fields = {"name": {"stringValue": "POO"}}

    document = client.patch_user_document("courses", "dcc203", fields=fields)

    request = calls[0]
    assert request.method == "PATCH"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data) == {"fields": fields}
    assert document == {"fields": fields}


def test_list_user_documents_follows_bounded_pagination() -> None:
    calls: list[Any] = []

    def transport(request: Any, _timeout: float) -> tuple[int, bytes]:
        calls.append(request)
        if len(calls) == 1:
            return 200, b'{"documents":[{"name":"one"}],"nextPageToken":"next"}'
        return 200, b'{"documents":[{"name":"two"}]}'

    client = FirestoreRestClient("project", "user", "token", transport=transport)

    documents = client.list_user_documents("courses")

    assert documents == [{"name": "one"}, {"name": "two"}]
    assert calls[0].full_url.endswith("/users/user/courses?pageSize=100")
    assert calls[1].full_url.endswith("/users/user/courses?pageSize=100&pageToken=next")


@pytest.mark.parametrize(
    "payload",
    [b'{"documents":"bad"}', b'{"documents":["bad"]}', b'{"nextPageToken":""}'],
)
def test_list_user_documents_rejects_malformed_pages(payload: bytes) -> None:
    client = FirestoreRestClient(
        "project", "user", "token", transport=lambda _request, _timeout: (200, payload)
    )

    with pytest.raises(FirestoreUnavailable):
        client.list_user_documents("courses")


def test_delete_user_document_accepts_empty_success() -> None:
    calls: list[Any] = []

    def transport(request: Any, _timeout: float) -> tuple[int, bytes]:
        calls.append(request)
        return 204, b""

    client = FirestoreRestClient("project", "user", "token", transport=transport)

    client.delete_user_document("courses", "course-1")

    assert calls[0].method == "DELETE"


def test_delete_user_documents_commits_one_bounded_batch() -> None:
    calls: list[Any] = []

    def transport(request: Any, _timeout: float) -> tuple[int, bytes]:
        calls.append(request)
        return 200, b'{"writeResults":[]}'

    client = FirestoreRestClient("project", "user", "token", transport=transport)

    client.delete_user_documents(
        [("courses", "course-1", "sessions", "session-1"), ("courses", "course-1")]
    )

    assert calls[0].method == "POST"
    assert calls[0].full_url.endswith("/databases/(default)/documents:commit")
    assert json.loads(calls[0].data) == {
        "writes": [
            {
                "delete": (
                    "projects/project/databases/(default)/documents/"
                    "users/user/courses/course-1/sessions/session-1"
                )
            },
            {
                "delete": (
                    "projects/project/databases/(default)/documents/users/user/courses/course-1"
                )
            },
        ]
    }


@pytest.mark.parametrize("paths", [[], [("courses", "id")] * 501, [("courses",)]])
def test_delete_user_documents_rejects_unsafe_batches(
    paths: list[tuple[str, ...]],
) -> None:
    client = FirestoreRestClient("project", "user", "token")

    with pytest.raises(ValueError):
        client.delete_user_documents(paths)


@pytest.mark.parametrize("status", [401, 403])
def test_request_maps_auth_failures_without_exposing_response(status: int) -> None:
    client = FirestoreRestClient(
        "project",
        "user",
        "token",
        transport=lambda _request, _timeout: (status, b'{"private":"details"}'),
    )

    with pytest.raises(FirestoreAccessDenied, match="Firestore denied the request") as caught:
        client.get_user_document("courses", "dcc203")

    assert "private" not in str(caught.value)


def test_request_maps_not_found_and_unavailable_responses() -> None:
    not_found = FirestoreRestClient(
        "project",
        "user",
        "token",
        transport=lambda _request, _timeout: (404, b"private"),
    )
    unavailable = FirestoreRestClient(
        "project",
        "user",
        "token",
        transport=lambda _request, _timeout: (503, b"private"),
    )

    with pytest.raises(FirestoreNotFound, match="document was not found"):
        not_found.get_user_document("courses", "dcc203")
    with pytest.raises(FirestoreUnavailable, match="Firestore is unavailable"):
        unavailable.get_user_document("courses", "dcc203")


def test_request_maps_bad_requests_without_exposing_response() -> None:
    client = FirestoreRestClient(
        "project",
        "user",
        "token",
        transport=lambda _request, _timeout: (400, b'{"token":"private"}'),
    )

    with pytest.raises(FirestoreRequestRejected, match="Firestore rejected the request") as caught:
        client.get_user_document("courses", "dcc203")

    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (418, b"{}"),
        (200, b"not-json"),
        (200, b"[]"),
        (200, b"x" * 1_048_577),
    ],
    ids=["unexpected-status", "invalid-json", "non-object-json", "oversized-response"],
)
def test_request_rejects_unexpected_responses(status: int, payload: bytes) -> None:
    client = FirestoreRestClient(
        "project",
        "user",
        "token",
        transport=lambda _request, _timeout: (status, payload),
    )

    with pytest.raises(FirestoreUnavailable):
        client.get_user_document("courses", "dcc203")


def test_request_sanitizes_transport_failures() -> None:
    def fail(_request: Any, _timeout: float) -> tuple[int, bytes]:
        raise OSError("signed-id-token")

    client = FirestoreRestClient("project", "user", "signed-id-token", transport=fail)

    with pytest.raises(FirestoreUnavailable) as caught:
        client.get_user_document("courses", "dcc203")

    assert "signed-id-token" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    ("project_id", "user_id", "id_token", "segments"),
    [
        ("", "user", "token", ("courses", "dcc203")),
        ("project/other", "user", "token", ("courses", "dcc203")),
        ("project", "", "token", ("courses", "dcc203")),
        ("project", "other/user", "token", ("courses", "dcc203")),
        ("project", "user", "", ("courses", "dcc203")),
        ("project", "user", "x" * 16_385, ("courses", "dcc203")),
        ("project", "user", "token", ()),
        ("project", "user", "token", ("courses",)),
        ("project", "user", "token", ("courses", "bad/id")),
        ("project", "user", "token", ("courses", " x")),
    ],
)
def test_client_rejects_invalid_configuration_and_paths(
    project_id: str,
    user_id: str,
    id_token: str,
    segments: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        client = FirestoreRestClient(project_id, user_id, id_token)
        client.get_user_document(*segments)


def test_client_accepts_only_local_firestore_emulator_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    client = FirestoreRestClient("demo-project", "user", "token")
    assert client.base_url == "http://127.0.0.1:8080/v1"

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "metadata.google.internal")
    with pytest.raises(ValueError, match="invalid Firestore emulator host"):
        FirestoreRestClient("demo-project", "user", "token")


@pytest.mark.parametrize("timeout_seconds", [0, 31])
def test_client_rejects_timeout_outside_safe_range(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="invalid Firestore timeout"):
        FirestoreRestClient(
            "demo-project",
            "user",
            "token",
            timeout_seconds=timeout_seconds,
        )


def test_patch_rejects_invalid_or_oversized_payloads() -> None:
    client = FirestoreRestClient("project", "user", "token")

    with pytest.raises(ValueError, match="JSON serializable"):
        client.patch_user_document("courses", "dcc203", fields={"bad": object()})
    with pytest.raises(ValueError, match="too large"):
        client.patch_user_document(
            "courses",
            "dcc203",
            fields={"name": {"stringValue": "x" * 1_048_577}},
        )


def test_default_transport_normalizes_success_and_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return b"success"

    monkeypatch.setattr(firestore_module, "urlopen", lambda *_args, **_kwargs: Response())
    request = firestore_module.Request("https://example.test")
    assert firestore_module._urlopen_transport(request, 10) == (200, b"success")

    error = HTTPError("https://example.test", 403, "denied", {}, BytesIO(b"denied"))

    def raise_error(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(firestore_module, "urlopen", raise_error)
    assert firestore_module._urlopen_transport(request, 10) == (403, b"denied")
