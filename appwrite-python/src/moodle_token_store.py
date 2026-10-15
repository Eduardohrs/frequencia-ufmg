"""Encrypted persistence for Moodle's file-scoped and webservice tokens."""

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

TOKEN_LIFETIME_SECONDS = 180 * 24 * 60 * 60
_MAX_TOKEN_LENGTH = 256
_NONCE_BYTES = 12
_SCHEMA_VERSION = 1
_USER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_TOKEN = re.compile(r"[A-Za-z0-9]{16,256}")
_TERM = re.compile(r"20[2-9][0-9]-[12]")


class InvalidMoodleTokens(Exception):
    """Raised when Moodle credentials cannot safely enter storage."""


class MoodleAuthorizationRequired(Exception):
    """Raised when the user must authorize Moodle downloads again."""


class MoodleTokenStoreUnavailable(Exception):
    """Raised when encrypted Moodle token persistence is unavailable."""


@dataclass(frozen=True)
class MoodleTokens:
    webservice_token: str
    private_token: str
    term: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class MoodleTokenMetadata:
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class _EncryptedMoodleTokens:
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


class MoodleTokenCipher:
    """Seal Moodle credentials with a purpose-specific AES-GCM context."""

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
            raise ValueError("invalid Moodle token encryption keys")
        self._keys = dict(keys)
        self._active_version = active_version
        self._nonce_factory = nonce_factory

    def seal(
        self,
        user_id: str,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        now: int,
    ) -> _EncryptedMoodleTokens:
        _validate(user_id, webservice_token, private_token, term, now)
        expires_at = now + TOKEN_LIFETIME_SECONDS
        plaintext = json.dumps(
            {
                "schema_version": _SCHEMA_VERSION,
                "webservice_token": webservice_token,
                "private_token": private_token,
                "term": term,
                "created_at": now,
                "expires_at": expires_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        nonce = self._nonce_factory(_NONCE_BYTES)
        if len(nonce) != _NONCE_BYTES:
            raise ValueError("invalid Moodle token nonce")
        ciphertext = AESGCM(self._keys[self._active_version]).encrypt(
            nonce,
            plaintext,
            _associated_data(user_id),
        )
        return _EncryptedMoodleTokens(
            key_version=self._active_version,
            nonce=_encode(nonce),
            ciphertext=_encode(ciphertext),
            expires_at=expires_at,
            updated_at=now,
        )

    def open(self, user_id: str, row: Mapping[str, object], *, now: int) -> MoodleTokens:
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
            nonce = _decode(_string(row["nonce"]))
            plaintext = AESGCM(self._keys[key_version]).decrypt(
                nonce,
                _decode(_string(row["ciphertext"])),
                _associated_data(user_id),
            )
            payload = json.loads(plaintext)
            if set(payload) != {
                "schema_version",
                "webservice_token",
                "private_token",
                "term",
                "created_at",
                "expires_at",
            }:
                raise ValueError
            created_at = payload["created_at"]
            if (
                payload["schema_version"] != _SCHEMA_VERSION
                or payload["expires_at"] != expires_at
                or type(created_at) is not int
                or created_at + TOKEN_LIFETIME_SECONDS != expires_at
            ):
                raise ValueError
            _validate(
                user_id,
                payload["webservice_token"],
                payload["private_token"],
                payload["term"],
                created_at,
            )
        except (
            InvalidTag,
            InvalidMoodleTokens,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            raise MoodleAuthorizationRequired("Moodle authorization required") from None
        return MoodleTokens(
            webservice_token=payload["webservice_token"],
            private_token=payload["private_token"],
            term=payload["term"],
            created_at=created_at,
            expires_at=expires_at,
        )


class AppwriteMoodleTokenStore:
    """Persist one encrypted Moodle token set per Firebase identity."""

    def __init__(
        self,
        tables: Any,
        *,
        database_id: str,
        table_id: str,
        cipher: MoodleTokenCipher,
        index_key: bytes,
    ) -> None:
        if not database_id or not table_id or len(index_key) != 32:
            raise ValueError("invalid Moodle token store configuration")
        self._tables = tables
        self._database_id = database_id
        self._table_id = table_id
        self._cipher = cipher
        self._index_key = index_key

    def save(
        self,
        user_id: str,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        now: int,
    ) -> MoodleTokenMetadata:
        encrypted = self._cipher.seal(
            user_id,
            webservice_token=webservice_token,
            private_token=private_token,
            term=term,
            now=now,
        )
        try:
            self._tables.upsert_row(
                self._database_id,
                self._table_id,
                self._row_id(user_id),
                encrypted.to_row(),
                permissions=[],
            )
        except AppwriteException:
            raise MoodleTokenStoreUnavailable("Moodle token store unavailable") from None
        return MoodleTokenMetadata(now, encrypted.expires_at)

    def load(self, user_id: str, *, now: int) -> MoodleTokens | None:
        row_id = self._row_id(user_id)
        try:
            row = self._tables.get_row(self._database_id, self._table_id, row_id)
        except AppwriteException as error:
            if error.code == 404:
                return None
            raise MoodleTokenStoreUnavailable("Moodle token store unavailable") from None
        try:
            return self._cipher.open(user_id, row.data, now=now)
        except MoodleAuthorizationRequired:
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
            raise MoodleTokenStoreUnavailable("Moodle token store unavailable") from None

    def _row_id(self, user_id: str) -> str:
        if _USER_ID.fullmatch(user_id) is None:
            raise InvalidMoodleTokens("invalid Moodle token input")
        digest = hmac_new(
            self._index_key,
            b"moodle-token\0" + user_id.encode(),
            sha256,
        ).hexdigest()
        return f"m_{digest[:32]}"


def _validate(
    user_id: str,
    webservice_token: object,
    private_token: object,
    term: object,
    now: int,
) -> None:
    if (
        _USER_ID.fullmatch(user_id) is None
        or not isinstance(webservice_token, str)
        or _TOKEN.fullmatch(webservice_token) is None
        or len(webservice_token) > _MAX_TOKEN_LENGTH
        or not isinstance(private_token, str)
        or _TOKEN.fullmatch(private_token) is None
        or len(private_token) > _MAX_TOKEN_LENGTH
        or not isinstance(term, str)
        or _TERM.fullmatch(term) is None
        or type(now) is not int
        or now < 0
    ):
        raise InvalidMoodleTokens("invalid Moodle token input")


def _associated_data(user_id: str) -> bytes:
    return b"frequencia-ufmg:moodle-token:v1\0" + user_id.encode()


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _encode(value: bytes) -> str:
    return b64encode(value).decode()


def _decode(value: str) -> bytes:
    return b64decode(value, validate=True)
