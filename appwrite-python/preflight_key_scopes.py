"""Read-only preflight of the Appwrite API key used by the storage provisioner.

Runs manually via the ``Preflight Appwrite key scopes (read-only)`` workflow.
It lists project API key metadata (names + scopes only — secret values are
compared in-process and NEVER printed) and probes read access, then reports
whether the key carries the schema scopes that ``setup_storage.py`` needs:

- modern:  tables.write + columns.write + indexes.write  (+ .read counterparts)
- legacy:  databases.write + collections.write + attributes.write + indexes.write

Exit codes: 0 = sufficient or undetermined, 2 = insufficient, 1 = probe error.
"""

import json
import os
from typing import Any

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.services.databases import Databases
from appwrite.services.project import Project

MODERN_WRITE = {"tables.write", "columns.write", "indexes.write"}
MODERN_READ = {"tables.read", "columns.read", "indexes.read"}
LEGACY_WRITE = {"databases.write", "collections.write", "attributes.write", "indexes.write"}
LEGACY_READ = {"databases.read", "collections.read", "attributes.read", "indexes.read"}


def collect_report(client: Client, key: str) -> dict[str, Any]:
    """Gather key metadata and read probes; never include secret values."""
    report: dict[str, Any] = {"probes": {}}
    used_scopes: set[str] | None = None
    try:
        keys = Project(client).list_keys()
    except AppwriteException as error:
        report["probes"]["list_keys"] = {
            "ok": False,
            "code": error.code,
            "type": error.type,
        }
    else:
        entries = []
        for entry in keys.to_dict().get("keys", []):
            scopes = sorted(str(scope) for scope in entry.get("scopes", []))
            entries.append({"name": entry.get("name"), "scopes": scopes})
            if entry.get("secret") == key:  # in-process match only, never printed
                used_scopes = set(scopes)
        report["keys"] = entries
    try:
        databases = Databases(client).list()
        report["probes"]["list_databases"] = {
            "ok": True,
            "count": databases.to_dict().get("total"),
        }
    except AppwriteException as error:
        report["probes"]["list_databases"] = {
            "ok": False,
            "code": error.code,
            "type": error.type,
        }
    if used_scopes is not None:
        report["used_key_scopes"] = sorted(used_scopes)
        report["sufficient"] = (
            used_scopes >= MODERN_WRITE and used_scopes >= MODERN_READ
        ) or (used_scopes >= LEGACY_WRITE and used_scopes >= LEGACY_READ)
    else:
        report["sufficient"] = None
    return report


def main() -> int:
    """Run the preflight from environment variables and print a JSON report."""
    endpoint = os.environ.get("APPWRITE_ENDPOINT") or ""
    project = os.environ.get("APPWRITE_PROJECT_ID") or ""
    admin = os.environ.get("APPWRITE_ADMIN_API_KEY") or ""
    deploy = os.environ.get("APPWRITE_DEPLOY_KEY") or ""
    if not endpoint or not project:
        print(json.dumps({"error": "APPWRITE_ENDPOINT and APPWRITE_PROJECT_ID are required"}))
        return 1
    if admin:
        key, label = admin, "APPWRITE_ADMIN_API_KEY"
    elif deploy:
        key, label = deploy, "APPWRITE_DEPLOY_KEY"
    else:
        print(json.dumps({"error": "no API key configured"}))
        return 1
    client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
    report = collect_report(client, key)
    report["key_source"] = label
    print(json.dumps(report, indent=2, sort_keys=True))
    sufficient = report.get("sufficient")
    if sufficient is True:
        print("VERDICT: SUFFICIENT - the configured key carries the schema scopes "
              "provisioning needs")
        return 0
    if sufficient is False:
        print("VERDICT: INSUFFICIENT - add tables.write+columns.write+indexes.write "
              "(or legacy databases/collections/attributes/indexes .write) to the key")
        return 2
    print("VERDICT: UNKNOWN - key could not be identified in the key list; check probes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
