"""Encrypted, user-bound persistence for short-lived UFMG SSO sessions."""

import json
import re
from base64 import b64decode, b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import new as hmac_new
from os import urandom
from typing import Any

from appwrite.exception import AppwriteException
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SESSION_LIFETIME_SECONDS = 9 * 60 * 60
MAX_TOKEN_LENGTH = 4_096
_NONCE_BYTES = 12
_SCHEMA_VERSION = 1
_USER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_KEY_NAME = re.compile(r"UFMG_SESSION_ENCRYPTION_KEY_V([1-9][0-9]*)")


class InvalidUFMGSession(Exception):
    """Raised when a session cannot safely enter encrypted storage."""


class UFMGReauthenticationRequired(Exception):
    """Raised when saved session material is expired or cannot be trusted."""


class UFMGSessionStoreUnavailable(Exception):
    """Raised when secure persistence cannot complete safely."""


@dataclass(frozen=True)
class UFMGSession:
    """The minimum reusable UFMG credential and its bounded lifetime."""

    token: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class UFMGSessionMetadata:
    """Non-secret session lifecycle details safe to return to callers."""

    created_at: int
    expires_at: int


@dataclass(frozen=True)
class EncryptedUFMGSession:
    """Ciphertext envelope safe to persist outside the client."""

    key_version: int
    nonce: str
    ciphertext: str
    expires_at: int
    updated_at: int

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "key_version": self.key_version,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class UFMGSessionSecrets:
    """Validated key material loaded only from the function environment."""

    encryption_keys: dict[int, bytes]
    active_version: int
    index_key: bytes

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "UFMGSessionSecrets":
        try:
            active_version = int(environment["UFMG_SESSION_ACTIVE_KEY_VERSION"])
            index_key = _decode_secret(environment["UFMG_SESSION_INDEX_KEY"])
            keys = {
                int(match.group(1)): _decode_secret(value)
                for name, value in environment.items()
                if (match := _KEY_NAME.fullmatch(name))
            }
            UFMGSessionCipher(keys, active_version=active_version)
            if len(index_key) != 32:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError("invalid UFMG session secret configuration") from None
        return cls(keys, active_version, index_key)


class UFMGSessionCipher:
    """Seal session material with AES-GCM and Firebase UID associated data."""

    def __init__(
        self,
        keys: Mapping[int, bytes],
        *,
        active_version: int,
        nonce_factory: Callable[[int], bytes] = urandom,
    ) -> None:
        if (
            not keys
            or active_version not in keys
            or any(type(version) is not int or version < 1 for version in keys)
            or any(len(key) != 32 for key in keys.values())
        ):
            raise ValueError("invalid UFMG session encryption keys")
        self._keys = dict(keys)
        self._active_version = active_version
        self._nonce_factory = nonce_factory

    def seal(self, user_id: str, token: str, *, now: int) -> EncryptedUFMGSession:
        _validate_input(user_id, token, now)
        expires_at = now + SESSION_LIFETIME_SECONDS
        plaintext = json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "token": token,
                "created_at": now,
                "expires_at": expires_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        nonce = self._nonce_factory(_NONCE_BYTES)
        if len(nonce) != _NONCE_BYTES:
            raise ValueError("invalid UFMG session nonce")
        ciphertext = AESGCM(self._keys[self._active_version]).encrypt(
            nonce,
            plaintext,
            _associated_data(user_id),
        )
        return EncryptedUFMGSession(
            key_version=self._active_version,
            nonce=_encode(nonce),
            ciphertext=_encode(ciphertext),
            expires_at=expires_at,
            updated_at=now,
        )

    def open(
        self,
        user_id: str,
        row: Mapping[str, object],
        *,
        now: int,
    ) -> UFMGSession:
        try:
            if set(row) != {
                "schema_version",
                "key_version",
                "nonce",
                "ciphertext",
                "expires_at",
                "updated_at",
            }:
                raise ValueError
            if row["schema_version"] != _SCHEMA_VERSION:
                raise ValueError
            key_version = row["key_version"]
            expires_at = row["expires_at"]
            if type(key_version) is not int or key_version not in self._keys:
                raise ValueError
            if type(expires_at) is not int or expires_at <= now:
                raise ValueError
            nonce = _decode(cast_string(row["nonce"]))
            ciphertext = _decode(cast_string(row["ciphertext"]))
            plaintext = AESGCM(self._keys[key_version]).decrypt(
                nonce,
                ciphertext,
                _associated_data(user_id),
            )
            payload = json.loads(plaintext)
            if set(payload) != {"schema_version", "token", "created_at", "expires_at"}:
                raise ValueError
            token = payload["token"]
            created_at = payload["created_at"]
            if (
                payload["schema_version"] != _SCHEMA_VERSION
                or payload["expires_at"] != expires_at
                or type(created_at) is not int
                or created_at < 0
                or created_at + SESSION_LIFETIME_SECONDS != expires_at
            ):
                raise ValueError
            _validate_input(user_id, token, created_at)
        except (
            InvalidTag,
            InvalidUFMGSession,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            raise UFMGReauthenticationRequired("UFMG reauthentication required") from None
        return UFMGSession(token=token, created_at=created_at, expires_at=expires_at)


class AppwriteUFMGSessionStore:
    """Persist one encrypted UFMG session per Firebase identity."""

    def __init__(
        self,
        tables: Any,
        *,
        database_id: str,
        table_id: str,
        cipher: UFMGSessionCipher,
        index_key: bytes,
    ) -> None:
        if not database_id or not table_id or len(index_key) != 32:
            raise ValueError("invalid UFMG session store configuration")
        self._tables = tables
        self._database_id = database_id
        self._table_id = table_id
        self._cipher = cipher
        self._index_key = index_key

    def save(self, user_id: str, token: str, *, now: int) -> UFMGSessionMetadata:
        encrypted = self._cipher.seal(user_id, token, now=now)
        try:
            self._tables.upsert_row(
                self._database_id,
                self._table_id,
                self._row_id(user_id),
                encrypted.to_row(),
                permissions=[],
            )
        except AppwriteException:
            raise UFMGSessionStoreUnavailable("UFMG session store unavailable") from None
        return UFMGSessionMetadata(now, encrypted.expires_at)

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        row_id = self._row_id(user_id)
        try:
            row = self._tables.get_row(self._database_id, self._table_id, row_id)
        except AppwriteException as error:
            if error.code == 404:
                return None
            raise UFMGSessionStoreUnavailable("UFMG session store unavailable") from None
        try:
            return self._cipher.open(user_id, row.data, now=now)
        except UFMGReauthenticationRequired:
            self._delete_row(row_id)
            raise

    def delete(self, user_id: str) -> None:
        self._delete_row(self._row_id(user_id))

    def _delete_row(self, row_id: str) -> None:
        try:
            self._tables.delete_row(self._database_id, self._table_id, row_id)
        except AppwriteException as error:
            if error.code == 404:
                return
            raise UFMGSessionStoreUnavailable("UFMG session store unavailable") from None

    def _row_id(self, user_id: str) -> str:
        if _USER_ID.fullmatch(user_id) is None:
            raise InvalidUFMGSession("invalid UFMG session input")
        digest = hmac_new(self._index_key, b"ufmg-session\0" + user_id.encode(), sha256).hexdigest()
        return f"u_{digest[:32]}"


class RequestCachedUFMGSessionStore:
    """Reuse one decrypted session snapshot inside a single function request."""

    def __init__(self, store: AppwriteUFMGSessionStore) -> None:
        self._store = store
        self._cache: dict[str, UFMGSession | None] = {}

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        cached = self._cache.get(user_id)
        if user_id in self._cache and (cached is None or cached.expires_at > now):
            return cached
        loaded = self._store.load(user_id, now=now)
        self._cache[user_id] = loaded
        return loaded

    def delete(self, user_id: str) -> None:
        self._store.delete(user_id)
        self._cache.pop(user_id, None)


def _validate_input(user_id: str, token: object, now: int) -> None:
    if (
        _USER_ID.fullmatch(user_id) is None
        or not isinstance(token, str)
        or not 8 <= len(token) <= MAX_TOKEN_LENGTH
        or any(character.isspace() for character in token)
        or type(now) is not int
        or now < 0
    ):
        raise InvalidUFMGSession("invalid UFMG session input")


def _associated_data(user_id: str) -> bytes:
    return b"frequencia-ufmg:ufmg-session:v1\0" + user_id.encode()


def _decode_secret(value: str) -> bytes:
    try:
        return b64decode(value, validate=True)
    except (TypeError, ValueError):
        raise ValueError("invalid UFMG session secret configuration") from None


def _encode(value: bytes) -> str:
    return b64encode(value).decode()


def _decode(value: str) -> bytes:
    return b64decode(value, validate=True)


def cast_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value
