"""Tests for the OPTIONAL operator-run storage provisioner (real SDK, mocked HTTP).

setup_storage.py is never called by CI or by the production deploy: it exists
only to prepare another environment manually, against an EXPLICIT target
database given by APPWRITE_STORAGE_DATABASE_ID (there is no default).
"""

import json

import pytest
from appwrite.client import Client
from appwrite.exception import AppwriteException

import setup_storage
from storage_schema import COLLECTION_SPECS

# Explicit target database used by the fakes; the operator script never defaults one.
DB = "test-database"
TS = "2024-01-01T00:00:00.000+00:00"


def _spec_keys(collection_id: str) -> tuple[set[str], set[str]]:
    spec = COLLECTION_SPECS[collection_id]
    return {a["key"] for a in spec["attributes"]}, {i["key"] for i in spec["indexes"]}


def _attribute_payload(key: str, type_: str = "string") -> dict:
    payload = {"key": key, "type": type_, "status": "available", "error": "",
               "required": True, "description": "", "array": False,
               "$createdAt": TS, "$updatedAt": TS}
    if type_ == "string":
        payload["size"] = 255
    return payload


def _index_payload(key: str) -> dict:
    return {"$id": key, "$createdAt": TS, "$updatedAt": TS, "key": key, "type": "key",
            "status": "available", "error": "", "description": "",
            "attributes": [], "lengths": []}


class FakeTransport:
    """Routes SDK client.call invocations to canned HTTP JSON responses.

    The target database always exists (the operator points at an existing
    database; creating a second database is not part of this flow).
    """

    def __init__(self, *, attributes: dict[str, set[str]] | None = None,
                 indexes: dict[str, set[str]] | None = None,
                 fail: AppwriteException | None = None) -> None:
        self.attributes = attributes or {}
        self.indexes = indexes or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.collections_created: set[str] = set()

    def __call__(self, method: str, path: str, headers=None, params=None,
                 response_type: str = "json") -> object:
        self.calls.append((method, path))
        if self.fail is not None:
            raise self.fail
        if path == f"/databases/{DB}" and method == "get":
            return {"$id": DB, "name": DB}
        if path == "/databases" and method == "post":
            raise AssertionError("operator provisioner must not create databases")
        if path == f"/databases/{DB}/collections" and method == "post":
            self.collections_created.add(str(params.get("collectionId", "")))
            return {"$id": str(params.get("collectionId", ""))}
        is_attributes_list = (
            path.startswith(f"/databases/{DB}/collections/")
            and path.endswith("/attributes")
            and method == "get"
        )
        if is_attributes_list:
            collection_id = path.split("/collections/")[1].split("/")[0]
            keys = self.attributes.get(collection_id, _spec_keys(collection_id)[0])
            types = {a["key"]: a["type"] for a in COLLECTION_SPECS[collection_id]["attributes"]}
            return {"total": len(keys),
                    "attributes": [_attribute_payload(key, types.get(key, "string"))
                                   for key in sorted(keys)]}
        if "/attributes/string" in path and method == "post":
            return _attribute_payload(str(params.get("key", "")), "string")
        if "/attributes/integer" in path and method == "post":
            return _attribute_payload(str(params.get("key", "")), "integer")
        is_indexes_list = (
            path.startswith(f"/databases/{DB}/collections/")
            and path.endswith("/indexes")
            and method == "get"
        )
        if is_indexes_list:
            collection_id = path.split("/collections/")[1].split("/")[0]
            keys = self.indexes.get(collection_id, _spec_keys(collection_id)[1])
            return {"total": len(keys), "indexes": [_index_payload(key) for key in sorted(keys)]}
        if path.endswith("/indexes") and method == "post":
            return _index_payload(str(params.get("key", "")))
        if path.startswith(f"/databases/{DB}/collections/") and method == "get":
            collection_id = path.split("/collections/")[1]
            if collection_id not in self.collections_created:
                raise AppwriteException("missing", code=404, type="collection_not_found")
            return {"$id": collection_id}
        raise AssertionError(f"unexpected call {method} {path}")


def _install(monkeypatch: pytest.MonkeyPatch, transport: FakeTransport,
             env: dict[str, str] | None = None) -> None:
    client = Client().set_endpoint("https://cloud.appwrite.io/v1").set_project("proj").set_key("admin")
    client.call = transport  # type: ignore[method-assign]
    monkeypatch.setattr(setup_storage, "Client", lambda: client)
    for name in ("APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_ADMIN_API_KEY",
                 "APPWRITE_STORAGE_DATABASE_ID", "APPWRITE_STORAGE_READY_TIMEOUT_SECONDS",
                 "APPWRITE_STORAGE_READY_POLL_INTERVAL_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {
        "APPWRITE_ENDPOINT": "https://cloud.appwrite.io/v1",
        "APPWRITE_PROJECT_ID": "proj",
        "APPWRITE_ADMIN_API_KEY": "admin-key",
        "APPWRITE_STORAGE_DATABASE_ID": DB,
        # bounded readiness wait so failure tests stay fast
        "APPWRITE_STORAGE_READY_TIMEOUT_SECONDS": "0.05",
        "APPWRITE_STORAGE_READY_POLL_INTERVAL_SECONDS": "0.01",
    }).items():
        monkeypatch.setenv(name, value)


def test_provision_creates_collections_in_the_explicit_existing_database(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    transport = FakeTransport()
    _install(monkeypatch, transport)

    assert setup_storage.main() == 0

    out = json.loads(capsys.readouterr().out)
    assert out["storage"]["database"] == "exists"
    assert out["storage"]["validated"] == sorted(COLLECTION_SPECS)
    # both collections created inside the EXPLICIT target database; the
    # database itself is never created by this operator script
    assert ("post", f"/databases/{DB}/collections") in transport.calls
    assert ("post", "/databases") not in transport.calls


def test_provision_is_idempotent_when_everything_exists(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    transport = FakeTransport()
    _install(monkeypatch, transport)
    assert setup_storage.main() == 0
    capsys.readouterr()

    transport.collections_created.update(COLLECTION_SPECS)
    calls_before = len(transport.calls)
    assert setup_storage.main() == 0

    out = json.loads(capsys.readouterr().out)
    assert out["storage"]["database"] == "exists"
    assert all(v == {"status": "exists"} for v in out["storage"]["collections"].values())
    # second run created nothing new
    assert ("post", f"/databases/{DB}/collections") not in transport.calls[calls_before:]


def test_provision_fails_when_a_required_attribute_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    missing = {cid: (keys - {"user_id"}, idxs) for cid, (keys, idxs) in
               ((cid, _spec_keys(cid)) for cid in COLLECTION_SPECS)}
    attributes = {cid: keys for cid, (keys, _idxs) in missing.items()}
    transport = FakeTransport(attributes=attributes)
    _install(monkeypatch, transport)
    transport.collections_created.update(COLLECTION_SPECS)

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "user_id" in err["error"]


def test_provision_fails_closed_on_service_error(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    transport = FakeTransport(fail=AppwriteException("down", code=500, type="general"))
    _install(monkeypatch, transport)

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "down" in err["error"] or "500" in err["error"]


def test_provision_requires_explicit_target_database_and_admin_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    # no APPWRITE_STORAGE_DATABASE_ID -> fail loudly, never default a database
    _install(monkeypatch, FakeTransport(), env={
        "APPWRITE_ENDPOINT": "https://x/v1",
        "APPWRITE_PROJECT_ID": "proj",
        "APPWRITE_ADMIN_API_KEY": "admin-key",
    })

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "APPWRITE_STORAGE_DATABASE_ID" in err["error"]

    # explicit database but no admin key -> fail loudly as well
    _install(monkeypatch, FakeTransport(), env={
        "APPWRITE_ENDPOINT": "https://x/v1",
        "APPWRITE_PROJECT_ID": "proj",
        "APPWRITE_STORAGE_DATABASE_ID": DB,
    })

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "APPWRITE_ADMIN_API_KEY" in err["error"]
