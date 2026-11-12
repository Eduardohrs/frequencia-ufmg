"""Tests for the read-only key-scope preflight (real SDK, mocked HTTP transport)."""

import json
from typing import Any

from appwrite.client import Client
from appwrite.exception import AppwriteException

import preflight_key_scopes as preflight

STAMP = "2025-01-01T00:00:00.000+00:00"
MODERN = ["tables.read", "tables.write", "columns.read", "columns.write",
          "indexes.read", "indexes.write", "functions.write"]
LEGACY = ["databases.read", "databases.write", "collections.read", "collections.write",
          "attributes.read", "attributes.write", "indexes.read", "indexes.write"]


def key_json(key_id: str, name: str, scopes: list[str], secret: str) -> dict[str, Any]:
    return {"$id": key_id, "$createdAt": STAMP, "$updatedAt": STAMP, "name": name,
            "description": "", "expire": "", "scopes": scopes, "secret": secret,
            "accessedAt": STAMP, "sdks": []}


def database_json(database_id: str) -> dict[str, Any]:
    return {"$id": database_id, "name": database_id, "$createdAt": STAMP,
            "$updatedAt": STAMP, "enabled": True}


class KeysTransport:
    def __init__(self, keys: list[dict[str, Any]], *, fail_keys: Exception | None = None,
                 fail_databases: Exception | None = None) -> None:
        self.keys = keys
        self.fail_keys = fail_keys
        self.fail_databases = fail_databases

    def __call__(self, method: str, path: str, headers=None, params=None,
                 response_type: str = "json") -> Any:
        if path == "/project/keys" and method == "get":
            if self.fail_keys is not None:
                raise self.fail_keys
            return {"total": len(self.keys), "keys": self.keys}
        if path == "/databases" and method == "get":
            if self.fail_databases is not None:
                raise self.fail_databases
            return {"total": 1, "databases": [database_json("frequencia_ufmg")]}
        raise AssertionError(f"unexpected transport call {method} {path}")


def make_client(transport: KeysTransport) -> Client:
    client = Client().set_endpoint("https://cloud.appwrite.io/v1").set_project("proj")
    client.call = transport  # type: ignore[method-assign]
    return client


def test_preflight_reports_sufficient_modern_scopes_and_never_leaks_secrets() -> None:
    transport = KeysTransport([
        key_json("k1", "deploy", MODERN, "deploy-secret-value"),
        key_json("k2", "other", ["users.read"], "other-secret-value"),
    ])
    report = preflight.collect_report(make_client(transport), "deploy-secret-value")
    assert report["sufficient"] is True
    assert report["used_key_scopes"] == sorted(MODERN)
    assert report["probes"]["list_databases"] == {"ok": True, "count": 1}
    assert [entry["name"] for entry in report["keys"]] == ["deploy", "other"]
    assert "secret" not in json.dumps(report)  # metadata only, never key values


def test_preflight_accepts_legacy_scopes_and_rejects_insufficient() -> None:
    legacy = KeysTransport([key_json("k1", "deploy", LEGACY, "s3cret")])
    report = preflight.collect_report(make_client(legacy), "s3cret")
    assert report["sufficient"] is True

    insufficient = KeysTransport([key_json("k1", "deploy", ["functions.write"], "s3cret")])
    report = preflight.collect_report(make_client(insufficient), "s3cret")
    assert report["sufficient"] is False


def test_preflight_unknown_when_key_not_identified_and_records_probe_failures() -> None:
    masked = KeysTransport([key_json("k1", "deploy", MODERN, "")])  # secret masked in list
    report = preflight.collect_report(make_client(masked), "real-value")
    assert report["sufficient"] is None

    failing = KeysTransport([], fail_keys=AppwriteException("denied", code=403, type="general"),
                            fail_databases=AppwriteException("denied", code=401, type="general"))
    report = preflight.collect_report(make_client(failing), "real-value")
    assert report["sufficient"] is None
    assert report["probes"]["list_keys"] == {"ok": False, "code": 403, "type": "general"}
    assert report["probes"]["list_databases"]["ok"] is False


def test_preflight_main_prefers_admin_key_and_maps_verdict_to_exit_code(
    monkeypatch, capsys
) -> None:
    for name in ("APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID", "APPWRITE_ADMIN_API_KEY",
                 "APPWRITE_DEPLOY_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert preflight.main() == 1  # nothing configured

    monkeypatch.setenv("APPWRITE_ENDPOINT", "https://cloud.appwrite.io/v1")
    monkeypatch.setenv("APPWRITE_PROJECT_ID", "proj")
    assert preflight.main() == 1  # no key

    monkeypatch.setenv("APPWRITE_DEPLOY_KEY", "deploy-secret-value")
    monkeypatch.setenv("APPWRITE_ADMIN_API_KEY", "admin-secret-value")
    transport = KeysTransport([key_json("k1", "admin", MODERN, "admin-secret-value")])
    monkeypatch.setattr(preflight, "Client", lambda: make_client(transport))
    assert preflight.main() == 0
    out = capsys.readouterr().out
    assert '"key_source": "APPWRITE_ADMIN_API_KEY"' in out
    assert "admin-secret-value" not in out and "deploy-secret-value" not in out
    assert "VERDICT: SUFFICIENT" in out

    insufficient = KeysTransport([key_json("k1", "admin", ["users.read"], "admin-secret-value")])
    monkeypatch.setattr(preflight, "Client", lambda: make_client(insufficient))
    assert preflight.main() == 2
    assert "VERDICT: INSUFFICIENT" in capsys.readouterr().out
