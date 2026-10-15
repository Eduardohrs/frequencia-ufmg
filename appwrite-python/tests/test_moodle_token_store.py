import json
from base64 import b64decode, b64encode
from dataclasses import dataclass
from typing import Any

import pytest
from appwrite.exception import AppwriteException
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from moodle_token_store import (
    AppwriteMoodleTokenStore,
    InvalidMoodleTokens,
    MoodleAuthorizationRequired,
    MoodleTokenCipher,
    MoodleTokenStoreUnavailable,
)


@dataclass
class _Row:
    data: dict[str, Any]


class _Tables:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def upsert_row(self, *args: Any, **kwargs: Any) -> _Row:
        self.calls.append(("upsert", args, kwargs))
        self.rows[args[2]] = dict(args[3])
        return _Row(self.rows[args[2]])

    def get_row(self, *args: Any, **kwargs: Any) -> _Row:
        self.calls.append(("get", args, kwargs))
        try:
            return _Row(self.rows[args[2]])
        except KeyError:
            raise AppwriteException("missing", 404) from None

    def delete_row(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", args, kwargs))
        try:
            del self.rows[args[2]]
        except KeyError:
            raise AppwriteException("missing", 404) from None
        return {}


def _store(tables: Any) -> AppwriteMoodleTokenStore:
    return AppwriteMoodleTokenStore(
        tables,
        database_id="security-db",
        table_id="ufmg-sessions",
        cipher=MoodleTokenCipher(
            {1: b"1" * 32},
            active_version=1,
            nonce_factory=lambda size: b"m" * size,
        ),
        index_key=b"i" * 32,
    )


def test_tokens_are_encrypted_user_bound_and_retained_for_at_most_180_days() -> None:
    tables = _Tables()
    store = _store(tables)

    metadata = store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1_000,
    )

    assert metadata.expires_at == 1_000 + 180 * 24 * 60 * 60
    row_id, row = next(iter(tables.rows.items()))
    serialized = repr((row_id, row))
    assert row_id.startswith("m_") and len(row_id) == 34
    assert "owner" not in serialized
    assert "bbbbbbbbbbbbbbbb" not in serialized
    assert "aaaaaaaaaaaaaaaa" not in serialized
    assert tables.calls[0][2]["permissions"] == []

    restored = store.load("owner", now=1_001)
    assert restored is not None
    assert restored.webservice_token == "bbbbbbbbbbbbbbbb"
    assert restored.private_token == "aaaaaaaaaaaaaaaa"
    assert restored.term == "2026-2"


def test_ciphertext_cannot_be_replayed_as_an_ufmg_session() -> None:
    tables = _Tables()
    store = _store(tables)
    store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1_000,
    )
    row = next(iter(tables.rows.values()))
    nonce = b64decode(row["nonce"])

    with pytest.raises(InvalidTag):
        AESGCM(b"1" * 32).decrypt(
            nonce,
            b64decode(row["ciphertext"]),
            b"frequencia-ufmg:ufmg-session:v1\0owner",
        )


def test_expired_or_tampered_tokens_are_removed_and_require_authorization() -> None:
    tables = _Tables()
    store = _store(tables)
    store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1_000,
    )
    row = next(iter(tables.rows.values()))
    row["expires_at"] = 1_001

    with pytest.raises(MoodleAuthorizationRequired):
        store.load("owner", now=1_001)

    assert tables.rows == {}


def test_malformed_plaintext_is_rejected_without_exposing_tokens() -> None:
    tables = _Tables()
    store = _store(tables)
    store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1_000,
    )
    row = next(iter(tables.rows.values()))
    nonce = b64decode(row["nonce"])
    row["ciphertext"] = b64encode(
        AESGCM(b"1" * 32).encrypt(
            nonce,
            json.dumps({"unexpected": True}).encode(),
            b"frequencia-ufmg:moodle-token:v1\0owner",
        )
    ).decode()

    with pytest.raises(MoodleAuthorizationRequired) as caught:
        store.load("owner", now=1_001)

    assert "webservice" not in str(caught.value)
    assert tables.rows == {}


@pytest.mark.parametrize(
    ("user_id", "webservice_token", "private_token", "term", "now"),
    [
        ("invalid user", "bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", "2026-2", 1),
        ("owner", "short", "aaaaaaaaaaaaaaaa", "2026-2", 1),
        ("owner", "bbbbbbbbbbbbbbbb", "short", "2026-2", 1),
        ("owner", "bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", "20262", 1),
        ("owner", "bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", "2026-2", -1),
    ],
)
def test_invalid_tokens_are_rejected_before_storage(
    user_id: str,
    webservice_token: str,
    private_token: str,
    term: str,
    now: int,
) -> None:
    tables = _Tables()
    with pytest.raises(InvalidMoodleTokens):
        _store(tables).save(
            user_id,
            webservice_token=webservice_token,
            private_token=private_token,
            term=term,
            now=now,
        )
    assert tables.calls == []


def test_missing_and_delete_are_idempotent_and_store_failures_are_sanitized() -> None:
    tables = _Tables()
    store = _store(tables)
    assert store.load("owner", now=1) is None
    store.delete("owner")

    class _BrokenTables(_Tables):
        def upsert_row(self, *args: Any, **kwargs: Any) -> _Row:
            raise AppwriteException("private-key", 500)

    with pytest.raises(MoodleTokenStoreUnavailable) as caught:
        _store(_BrokenTables()).save(
            "owner",
            webservice_token="bbbbbbbbbbbbbbbb",
            private_token="aaaaaaaaaaaaaaaa",
            term="2026-2",
            now=1,
        )
    assert "private-key" not in str(caught.value)


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
    keys: dict[int, bytes],
    active_version: int,
    index_key: bytes,
) -> None:
    with pytest.raises(ValueError):
        AppwriteMoodleTokenStore(
            _Tables(),
            database_id="database",
            table_id="table",
            cipher=MoodleTokenCipher(keys, active_version=active_version),
            index_key=index_key,
        )


def test_rejects_invalid_nonce_source() -> None:
    cipher = MoodleTokenCipher(
        {1: b"1" * 32},
        active_version=1,
        nonce_factory=lambda _size: b"short",
    )
    with pytest.raises(ValueError):
        cipher.seal(
            "owner",
            webservice_token="bbbbbbbbbbbbbbbb",
            private_token="aaaaaaaaaaaaaaaa",
            term="2026-2",
            now=1,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"unexpected": True}),
        lambda row: row.update({"schema_version": 2}),
        lambda row: row.update({"key_version": 2}),
        lambda row: row.update({"nonce": 12}),
    ],
)
def test_malformed_envelopes_are_removed(mutation: Any) -> None:
    tables = _Tables()
    store = _store(tables)
    store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1,
    )
    mutation(next(iter(tables.rows.values())))
    with pytest.raises(MoodleAuthorizationRequired):
        store.load("owner", now=2)
    assert tables.rows == {}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": 2,
            "webservice_token": "bbbbbbbbbbbbbbbb",
            "private_token": "aaaaaaaaaaaaaaaa",
            "term": "2026-2",
            "created_at": 1,
            "expires_at": 1 + 180 * 24 * 60 * 60,
        },
        {
            "schema_version": 1,
            "webservice_token": "bbbbbbbbbbbbbbbb",
            "private_token": "aaaaaaaaaaaaaaaa",
            "term": "2026-2",
            "created_at": "1",
            "expires_at": 1 + 180 * 24 * 60 * 60,
        },
        {
            "schema_version": 1,
            "webservice_token": "short",
            "private_token": "aaaaaaaaaaaaaaaa",
            "term": "2026-2",
            "created_at": 1,
            "expires_at": 1 + 180 * 24 * 60 * 60,
        },
    ],
)
def test_malformed_decrypted_fields_are_removed(payload: dict[str, object]) -> None:
    tables = _Tables()
    store = _store(tables)
    store.save(
        "owner",
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        now=1,
    )
    row = next(iter(tables.rows.values()))
    nonce = b64decode(row["nonce"])
    row["ciphertext"] = b64encode(
        AESGCM(b"1" * 32).encrypt(
            nonce,
            json.dumps(payload).encode(),
            b"frequencia-ufmg:moodle-token:v1\0owner",
        )
    ).decode()
    with pytest.raises(MoodleAuthorizationRequired):
        store.load("owner", now=2)


def test_invalid_identity_and_storage_failures_fail_closed() -> None:
    tables = _Tables()
    store = _store(tables)
    with pytest.raises(InvalidMoodleTokens):
        store.load("invalid user", now=1)
    with pytest.raises(InvalidMoodleTokens):
        store.delete("invalid user")

    class BrokenRead(_Tables):
        def get_row(self, *args: Any, **kwargs: Any) -> _Row:
            raise AppwriteException("private-key", 500)

    with pytest.raises(MoodleTokenStoreUnavailable):
        _store(BrokenRead()).load("owner", now=1)

    class BrokenDelete(_Tables):
        def delete_row(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AppwriteException("private-key", 500)

    with pytest.raises(MoodleTokenStoreUnavailable):
        _store(BrokenDelete()).delete("owner")
