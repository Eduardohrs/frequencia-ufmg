"""Tests for the deploy-pipeline storage provisioner (real SDK, mocked HTTP)."""

import json

import pytest
from appwrite.client import Client
from appwrite.exception import AppwriteException

import setup_storage
from appwrite_storage import COLLECTION_SPECS, DATABASE_ID

DB = DATABASE_ID
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
    """Routes SDK client.call invocations to canned HTTP JSON responses."""

    def __init__(self, *, attributes: dict[str, set[str]] | None = None,
                 indexes: dict[str, set[str]] | None = None,
                 existing: bool = False, fail: AppwriteException | None = None) -> None:
        self.attributes = attributes or {}
        self.indexes = indexes or {}
        self.existing = existing
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.db_created = existing
        self.collections_created: set[str] = set(COLLECTION_SPECS) if existing else set()

    def __call__(self, method: str, path: str, headers=None, params=None,
                 response_type: str = "json") -> object:
        self.calls.append((method, path))
        if self.fail is not None:
            raise self.fail
        if path == f"/databases/{DB}" and method == "get":
            if not self.db_created:
                raise AppwriteException("missing", code=404, type="database_not_found")
            return {"$id": DB, "name": DB}
        if path == "/databases" and method == "post":
            self.db_created = True
            return {"$id": DB, "name": DB}
        if path == f"/databases/{DB}/collections" and method == "post":
            self.collections_created.add(str(params.get("collectionId", "")))
            return {"$id": str(params.get("collectionId", ""))}
        is_attributes_list = path.startswith(f"/databases/{DB}/collections/")
        is_attributes_list = is_attributes_list and path.endswith("/attributes")
        if is_attributes_list and method == "get":
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
        is_indexes_list = path.startswith(f"/databases/{DB}/collections/")
        is_indexes_list = is_indexes_list and path.endswith("/indexes")
        if is_indexes_list and method == "get":
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
                 "APPWRITE_FUNCTION_API_ENDPOINT", "APPWRITE_FUNCTION_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {
        "APPWRITE_ENDPOINT": "https://cloud.appwrite.io/v1",
        "APPWRITE_PROJECT_ID": "proj",
        "APPWRITE_ADMIN_API_KEY": "admin-key",
    }).items():
        monkeypatch.setenv(name, value)


def test_provision_creates_and_validates_storage(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    transport = FakeTransport(existing=False)
    _install(monkeypatch, transport)

    assert setup_storage.main() == 0

    out = json.loads(capsys.readouterr().out)
    assert out["storage"]["database"] == "created"
    assert out["storage"]["validated"] == sorted(COLLECTION_SPECS)
    # database created, both collections created, attributes/indexes listed for validation
    assert ("post", "/databases") in transport.calls
    assert ("post", f"/databases/{DB}/collections") in transport.calls


def test_provision_is_idempotent_when_everything_exists(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    transport = FakeTransport(existing=True)
    _install(monkeypatch, transport)

    assert setup_storage.main() == 0

    out = json.loads(capsys.readouterr().out)
    assert out["storage"]["database"] == "exists"
    assert all(v == {"status": "exists"} for v in out["storage"]["collections"].values())
    assert ("post", "/databases") not in transport.calls


def test_provision_fails_when_a_required_attribute_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    missing = {cid: (keys - {"user_id"}, idxs) for cid, (keys, idxs) in
               ((cid, _spec_keys(cid)) for cid in COLLECTION_SPECS)}
    attributes = {cid: keys for cid, (keys, _idxs) in missing.items()}
    transport = FakeTransport(existing=True, attributes=attributes)
    _install(monkeypatch, transport)

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "user_id" in err["error"]


def test_provision_fails_closed_on_service_error(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    transport = FakeTransport(fail=AppwriteException("down", code=500, type="general"))
    _install(monkeypatch, transport)

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "down" in err["error"] or "500" in err["error"]


def test_provision_requires_admin_credentials(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    _install(monkeypatch, FakeTransport(), env={"APPWRITE_ENDPOINT": "https://x/v1"})

    assert setup_storage.main() == 1

    err = json.loads(capsys.readouterr().err)
    assert "APPWRITE_ADMIN_API_KEY" in err["error"]
