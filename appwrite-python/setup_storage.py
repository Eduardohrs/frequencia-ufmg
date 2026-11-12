"""Idempotent Appwrite storage provisioner for the deploy pipeline.

Runs OUTSIDE the public function API (the /internal/storage/ensure route was
removed) with an administrative API key from the APPWRITE_ADMIN_API_KEY
secret — never with the runtime execution key, whose scopes stay limited to
execute + data access. Creates/validates the ``frequencia_ufmg`` database and
the ``schedule_pendencies`` / ``registration_drafts`` collections with every
required attribute and index before new clients are published.

Usage: python setup_storage.py   (env: APPWRITE_ENDPOINT,
APPWRITE_PROJECT_ID, APPWRITE_ADMIN_API_KEY)
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from appwrite.client import Client  # noqa: E402
from appwrite.services.databases import Databases  # noqa: E402

from appwrite_storage import (  # noqa: E402
    COLLECTION_SPECS,
    READY_POLL_INTERVAL_SECONDS,
    READY_TIMEOUT_SECONDS,
    StorageNotProvisioned,
    StorageUnavailable,
    ensure_appwrite_storage,
    validate_appwrite_storage,
)


def _ready_wait_options() -> dict[str, float]:
    """Readiness polling budget, overridable via environment for deploys/tests."""
    timeout = float(os.environ.get("APPWRITE_STORAGE_READY_TIMEOUT_SECONDS", READY_TIMEOUT_SECONDS))
    poll = float(
        os.environ.get("APPWRITE_STORAGE_READY_POLL_INTERVAL_SECONDS", READY_POLL_INTERVAL_SECONDS)
    )
    return {"poll_interval_seconds": poll, "timeout_seconds": timeout}


def provision() -> dict[str, Any]:
    """Ensure and then validate the storage resources; raise on any failure."""
    endpoint = (
        os.environ.get("APPWRITE_ENDPOINT")
        or os.environ.get("APPWRITE_FUNCTION_API_ENDPOINT")
        or ""
    )
    project = (
        os.environ.get("APPWRITE_PROJECT_ID")
        or os.environ.get("APPWRITE_FUNCTION_PROJECT_ID")
        or ""
    )
    key = os.environ.get("APPWRITE_ADMIN_API_KEY") or ""
    if not endpoint or not project or not key:
        raise ValueError(
            "APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID and APPWRITE_ADMIN_API_KEY are required"
        )
    client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
    databases = Databases(client)
    wait_options = _ready_wait_options()
    summary = ensure_appwrite_storage(databases, **wait_options)
    validate_appwrite_storage(databases, **wait_options)
    summary["validated"] = sorted(COLLECTION_SPECS)
    return summary


def main() -> int:
    """Run the provisioner; return a process exit code."""
    try:
        summary = provision()
    except (StorageNotProvisioned, StorageUnavailable, ValueError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps({"storage": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
