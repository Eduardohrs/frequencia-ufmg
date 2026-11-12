# Appwrite storage for schedule pendencies and registration drafts

The function persists schedule pendencies (`schedule_pendencies`) and
registration drafts (`registration_drafts`) in the **existing** database
configured as `SECURITY_DATABASE_ID` — the same database that already holds
the security/session tables. The runtime receives the database id explicitly
from configuration and never defaults to another database: if
`SECURITY_DATABASE_ID` is missing, repository construction fails loudly
(`SecurityStoreUnavailable`) instead of selecting a nonexistent database.

## One-time provisioning (already done in production, 2026-11-12)

Provisioning was performed **once, out-of-band, by an operator** using the
existing authorized Appwrite CLI session — no new API key or secret was
created, and no CI/deploy step provisions schema. Raw evidence (metadata only,
no credentials): `D:/Dev/Tools/vibe-tools/pr257-provisioning-evidence.json`.

- Project `6abf16a10001890f8b13`, database `6abf198900070a8fedc4` (the existing
  `SECURITY_DATABASE_ID`; it already contained `function_guards` and
  `ufmg_sessions`, both untouched).
- Creating a second database was **rejected** by Appwrite (free plan database
  limit reached), so the two collections were added to the existing database.
- `schedule_pendencies`: 12 attributes, 2 indexes, all `available`, 0 documents,
  `permissions=[]`, `documentSecurity=true`; raw metadata matches
  `storage_schema.COLLECTION_SPECS`.
- `registration_drafts`: 9 attributes, 3 indexes, all `available`, 0 documents,
  `permissions=[]`, `documentSecurity=true`; matches the versioned spec.
- Verified at `2026-11-12T11:11:35Z`. No existing records or collections were
  modified; no temporary document was created.

## Preparing another environment (optional, operator-run only)

`appwrite-python/storage_schema.py` (versioned `COLLECTION_SPECS` +
idempotent ensure/validate) and `appwrite-python/setup_storage.py` are
**not** part of the deployed function bundle (the deploy packages only
`appwrite-python/src/*.py`) and are never invoked by CI or the production
deploy. To prepare another environment manually, an operator runs:

```bash
APPWRITE_ENDPOINT=... APPWRITE_PROJECT_ID=... APPWRITE_ADMIN_API_KEY=... \
APPWRITE_STORAGE_DATABASE_ID=<existing-database-id> \
    python appwrite-python/setup_storage.py
```

The target database is **explicit** (`APPWRITE_STORAGE_DATABASE_ID` is
required; there is no default), and the admin key must carry schema-write
scopes (`tables.write + columns.write + indexes.write`, or the legacy
`databases/collections/attributes/indexes` write scopes). No new secret and
no paid-plan change are required for production — the collections above
already exist there.
