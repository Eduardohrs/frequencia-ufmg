"""OPTIONAL one-time, operator-run Appwrite storage provisioner.

NOT used by CI or by the production deploy (the deploy workflow never calls
this script and never needs an administrative key): production already has
the two collections in the existing database configured as
``SECURITY_DATABASE_ID`` — see ``docs/appwrite-storage.md`` for the
one-time provisioning evidence.

Use it only to prepare ANOTHER environment, manually, with an
administrative API key, against an EXPLICIT target database (there is no
default target):

    APPWRITE_ENDPOINT=... APPWRITE_PROJECT_ID=... APPWRITE_ADMIN_API_KEY=... \
    APPWRITE_STORAGE_DATABASE_ID=<existing-database-id> \
        python appwrite-python/setup_storage.py

The key must carry schema-write scopes (see
``storage_schema.PROVISIONING_KEY_SCOPES``). Creates/validates the
``schedule_pendencies`` / ``registration_drafts`` collections from the
versioned ``storage_schema.COLLECTION_SPECS``, idempotently.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from appwrite.client import Client  # noqa: E402
from appwrite.services.databases import Databases  # noqa: E402

from appwrite_storage import StorageNotProvisioned, StorageUnavailable  # noqa: E402
from storage_schema import (  # noqa: E402
    COLLECTION_SPECS,
    READY_POLL_INTERVAL_SECONDS,
    READY_TIMEOUT_SECONDS,
    ensure_appwrite_storage,
    validate_appwrite_storage,
)


def _ready_wait_options() -> dict[str, float]:
    """Readiness polling budget, overridable via environment for tests."""
    timeout = float(os.environ.get("APPWRITE_STORAGE_READY_TIMEOUT_SECONDS", READY_TIMEOUT_SECONDS))
    poll = float(
        os.environ.get("APPWRITE_STORAGE_READY_POLL_INTERVAL_SECONDS", READY_POLL_INTERVAL_SECONDS)
    )
    return {"poll_interval_seconds": poll, "timeout_seconds": timeout}


def provision() -> dict[str, Any]:
    """Ensure and then validate the storage resources; raise on any failure."""
    endpoint = os.environ.get("APPWRITE_ENDPOINT", "")
    project = os.environ.get("APPWRITE_PROJECT_ID", "")
    key = os.environ.get("APPWRITE_ADMIN_API_KEY", "")
    database_id = os.environ.get("APPWRITE_STORAGE_DATABASE_ID", "")
    if not endpoint or not project or not key or not database_id:
        raise ValueError(
            "APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_ADMIN_API_KEY and "
            "APPWRITE_STORAGE_DATABASE_ID (explicit target database) are required"
        )
    client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
    databases = Databases(client)
    wait_options = _ready_wait_options()
    summary = ensure_appwrite_storage(databases, database_id, **wait_options)
    validate_appwrite_storage(databases, database_id, **wait_options)
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
