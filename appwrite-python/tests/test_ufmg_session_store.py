import json
from base64 import b64decode, b64encode
from dataclasses import dataclass
from typing import Any

import pytest
from appwrite.exception import AppwriteException
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ufmg_session_store import (
    AppwriteUFMGSessionStore,
    InvalidUFMGSession,
    UFMGReauthenticationRequired,
    UFMGSessionCipher,
    UFMGSessionSecrets,
    UFMGSessionStoreUnavailable,
)


@dataclass
class Row:
    data: dict[str, Any]


class FakeTables:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def upsert_row(self, *args: Any, **kwargs: Any) -> Row:
        self.calls.append(("upsert", args, kwargs))
        self.rows[args[2]] = dict(args[3])
        return Row(self.rows[args[2]])

    def get_row(self, *args: Any, **kwargs: Any) -> Row:
        self.calls.append(("get", args, kwargs))
        try:
            return Row(self.rows[args[2]])
        except KeyError:
            raise AppwriteException("private missing", 404) from None

    def delete_row(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", args, kwargs))
        try:
            del self.rows[args[2]]
        except KeyError:
            raise AppwriteException("private missing", 404) from None
        return {}


def _cipher(*, active_version: int = 2) -> UFMGSessionCipher:
    return UFMGSessionCipher(
        {1: b"1" * 32, 2: b"2" * 32},
        active_version=active_version,
        nonce_factory=lambda size: b"n" * size,
    )


def _store(tables: Any, *, active_version: int = 2) -> AppwriteUFMGSessionStore:
    return AppwriteUFMGSessionStore(
        tables,
        database_id="security-db",
        table_id="ufmg-sessions",
        cipher=_cipher(active_version=active_version),
        index_key=b"i" * 32,
    )


def _replace_encrypted_payload(row: dict[str, Any], payload: object) -> None:
    nonce = b64decode(row["nonce"])
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    row["ciphertext"] = b64encode(
        AESGCM(b"2" * 32).encrypt(
            nonce,
            plaintext,
            b"frequencia-ufmg:ufmg-session:v1\0owner",
        )
    ).decode()


def test_save_encrypts_one_short_lived_session_without_pii() -> None:
    tables = FakeTables()
    store = _store(tables)

    session = store.save("private-firebase-uid", "private-ltpa-token", now=1_000)

    assert session.created_at == 1_000
    assert session.expires_at == 1_000 + 9 * 60 * 60
    assert not hasattr(session, "token")
    assert len(tables.rows) == 1
    row_id, row = next(iter(tables.rows.items()))
    serialized = repr((row_id, row))
    assert row_id.startswith("u_") and len(row_id) == 34
    assert "private-firebase-uid" not in serialized
    assert "private-ltpa-token" not in serialized
    assert row == {
        "schema_version": 1,
        "key_version": 2,
        "nonce": "bm5ubm5ubm5ubm5u",
        "ciphertext": row["ciphertext"],
        "expires_at": 33_400,
        "updated_at": 1_000,
    }
    assert tables.calls[0][2]["permissions"] == []


def test_load_round_trips_and_binds_ciphertext_to_the_firebase_user() -> None:
    tables = FakeTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)

    restored = store.load("owner", now=1_001)

    assert restored is not None
    assert restored.token == "session-token"
    assert restored.created_at == 1_000
    assert store.load("other-user", now=1_001) is None


def test_old_key_remains_readable_during_rotation() -> None:
    tables = FakeTables()
    _store(tables, active_version=1).save("owner", "old-token", now=1_000)

    restored = _store(tables, active_version=2).load("owner", now=1_001)

    assert restored is not None
    assert restored.token == "old-token"


def test_expired_session_is_deleted_and_requires_reauthentication() -> None:
    tables = FakeTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)

    with pytest.raises(UFMGReauthenticationRequired):
        store.load("owner", now=33_400)

    assert tables.rows == {}
    assert tables.calls[-1][0] == "delete"


@pytest.mark.parametrize("field", ["nonce", "ciphertext", "expires_at", "key_version"])
def test_tampered_or_malformed_session_fails_closed_and_is_removed(field: str) -> None:
    tables = FakeTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)
    row = next(iter(tables.rows.values()))
    row[field] = "tampered" if field != "expires_at" else 33_399

    with pytest.raises(UFMGReauthenticationRequired) as caught:
        store.load("owner", now=1_001)

    assert "session-token" not in str(caught.value)
    assert tables.rows == {}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"unexpected": True}),
        lambda row: row.update({"schema_version": 2}),
        lambda row: row.update({"nonce": 12}),
    ],
)
def test_malformed_envelopes_require_reauthentication(mutation: Any) -> None:
    tables = FakeTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)
    mutation(next(iter(tables.rows.values())))

    with pytest.raises(UFMGReauthenticationRequired):
        store.load("owner", now=1_001)

    assert tables.rows == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        {
            "schema_version": 2,
            "token": "session-token",
            "created_at": 1_000,
            "expires_at": 33_400,
        },
        {
            "schema_version": 1,
            "token": "session-token",
            "created_at": "1000",
            "expires_at": 33_400,
        },
        {
            "schema_version": 1,
            "token": "session-token",
            "created_at": -1,
            "expires_at": 33_400,
        },
        {
            "schema_version": 1,
            "token": "short",
            "created_at": 1_000,
            "expires_at": 33_400,
        },
    ],
)
def test_malformed_decrypted_payloads_require_reauthentication(payload: object) -> None:
    tables = FakeTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)
    _replace_encrypted_payload(next(iter(tables.rows.values())), payload)

    with pytest.raises(UFMGReauthenticationRequired):
        store.load("owner", now=1_001)

    assert tables.rows == {}


def test_missing_session_and_idempotent_delete_do_not_fail() -> None:
    tables = FakeTables()
    store = _store(tables)

    assert store.load("owner", now=1_000) is None
    store.delete("owner")

    assert [call[0] for call in tables.calls] == ["get", "delete"]


@pytest.mark.parametrize(
    ("user_id", "token", "now"),
    [
        ("", "valid-token", 1),
        ("owner", "short", 1),
        ("owner", "x" * 4_097, 1),
        ("owner", "valid-token", -1),
        ("owner\nother", "valid-token", 1),
    ],
)
def test_save_rejects_invalid_inputs(user_id: str, token: str, now: int) -> None:
    with pytest.raises(InvalidUFMGSession):
        _store(FakeTables()).save(user_id, token, now=now)


def test_load_and_delete_reject_invalid_identity_before_storage_access() -> None:
    tables = FakeTables()
    store = _store(tables)

    with pytest.raises(InvalidUFMGSession):
        store.load("invalid user", now=1)
    with pytest.raises(InvalidUFMGSession):
        store.delete("invalid user")

    assert tables.calls == []


def test_rejects_invalid_nonce_source() -> None:
    cipher = UFMGSessionCipher(
        {1: b"1" * 32},
        active_version=1,
        nonce_factory=lambda _size: b"short",
    )

    with pytest.raises(ValueError):
        cipher.seal("owner", "session-token", now=1)


@pytest.mark.parametrize(
    ("keys", "active_version", "index_key"),
    [
        ({}, 1, b"i" * 32),
        ({1: b"short"}, 1, b"i" * 32),
        ({1: b"1" * 32}, 2, b"i" * 32),
        ({1: b"1" * 32}, 1, b"short"),
    ],
)
def test_rejects_unsafe_cryptographic_configuration(
    keys: dict[int, bytes], active_version: int, index_key: bytes
) -> None:
    with pytest.raises(ValueError):
        AppwriteUFMGSessionStore(
            FakeTables(),
            database_id="database",
            table_id="table",
            cipher=UFMGSessionCipher(keys, active_version=active_version),
            index_key=index_key,
        )


def test_store_failures_are_sanitized() -> None:
    class BrokenTables(FakeTables):
        def upsert_row(self, *args: Any, **kwargs: Any) -> Row:
            raise AppwriteException("private-api-key", 500)

    with pytest.raises(UFMGSessionStoreUnavailable) as caught:
        _store(BrokenTables()).save("owner", "session-token", now=1_000)

    assert "private-api-key" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_read_failures_are_sanitized() -> None:
    class BrokenTables(FakeTables):
        def get_row(self, *args: Any, **kwargs: Any) -> Row:
            raise AppwriteException("private-api-key", 500)

    with pytest.raises(UFMGSessionStoreUnavailable) as caught:
        _store(BrokenTables()).load("owner", now=1_000)

    assert "private-api-key" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_invalid_rows_and_delete_failures_are_sanitized() -> None:
    class BrokenTables(FakeTables):
        def delete_row(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AppwriteException("private-api-key", 500)

    tables = BrokenTables()
    store = _store(tables)
    store.save("owner", "session-token", now=1_000)
    next(iter(tables.rows.values()))["ciphertext"] = "invalid"

    with pytest.raises(UFMGSessionStoreUnavailable) as caught:
        store.load("owner", now=1_001)

    assert "private-api-key" not in str(caught.value)


def test_secrets_are_loaded_from_strict_base64_without_exposing_values() -> None:
    secrets = UFMGSessionSecrets.from_environment(
        {
            "UFMG_SESSION_ACTIVE_KEY_VERSION": "2",
            "UFMG_SESSION_ENCRYPTION_KEY_V1": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
            "UFMG_SESSION_ENCRYPTION_KEY_V2": "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=",
            "UFMG_SESSION_INDEX_KEY": "aWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWk=",
        }
    )

    assert secrets.active_version == 2
    assert secrets.encryption_keys == {1: b"1" * 32, 2: b"2" * 32}
    assert secrets.index_key == b"i" * 32


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"UFMG_SESSION_ACTIVE_KEY_VERSION": "private"},
        {
            "UFMG_SESSION_ACTIVE_KEY_VERSION": "1",
            "UFMG_SESSION_ENCRYPTION_KEY_V1": "not-base64",
            "UFMG_SESSION_INDEX_KEY": "not-base64",
        },
        {
            "UFMG_SESSION_ACTIVE_KEY_VERSION": "1",
            "UFMG_SESSION_ENCRYPTION_KEY_V1": "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
            "UFMG_SESSION_INDEX_KEY": "c2hvcnQ=",
        },
    ],
)
def test_invalid_secret_configuration_fails_closed(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError) as caught:
        UFMGSessionSecrets.from_environment(environment)

    assert "not-base64" not in str(caught.value)
