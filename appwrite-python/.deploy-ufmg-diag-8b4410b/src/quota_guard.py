"""Shared replay and fixed-window guards backed by Appwrite TablesDB."""

import re
from hashlib import sha256
from typing import Any

from appwrite.exception import AppwriteException


class ReplayDetected(Exception):
    """Raised when a limited-use App Check token is reused."""


class RateLimitExceeded(Exception):
    """Raised when a user exceeds the shared request budget."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


class SecurityStoreUnavailable(Exception):
    """Raised when the shared guard cannot fail closed safely."""


class AppwriteSecurityStore:
    """Consume single-use token digests and per-user request budgets."""

    def __init__(
        self,
        tables: Any,
        *,
        database_id: str,
        table_id: str,
        rate_limit: int,
        window_seconds: int,
    ) -> None:
        if not database_id or not table_id:
            raise ValueError("security store IDs are required")
        if not 1 <= rate_limit <= 1_000:
            raise ValueError("rate limit must be between 1 and 1000")
        if not 1 <= window_seconds <= 3_600:
            raise ValueError("window must be between 1 and 3600 seconds")
        self._tables = tables
        self._database_id = database_id
        self._table_id = table_id
        self._rate_limit = rate_limit
        self._window_seconds = window_seconds

    def consume(
        self,
        *,
        token_digest: str,
        user_id: str,
        route: str,
        expires_at: int,
        now: int,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", token_digest) is None:
            raise ValueError("invalid token digest")
        if not user_id or not route.startswith("/") or expires_at <= now:
            raise ValueError("invalid security guard input")

        try:
            self._tables.create_row(
                self._database_id,
                self._table_id,
                f"t_{token_digest[:32]}",
                {"kind": "replay", "count": 1, "expires_at": expires_at},
                permissions=[],
            )
        except AppwriteException as error:
            if error.code == 409:
                raise ReplayDetected("token already consumed") from None
            raise SecurityStoreUnavailable("security store unavailable") from None

        window_start = now - now % self._window_seconds
        retry_after = self._window_seconds - (now - window_start)
        rate_key = sha256(f"{user_id}\0{route}\0{window_start}".encode()).hexdigest()[:32]
        row_id = f"r_{rate_key}"
        try:
            row = self._tables.create_row(
                self._database_id,
                self._table_id,
                row_id,
                {
                    "kind": "rate",
                    "count": 1,
                    "expires_at": window_start + self._window_seconds,
                },
                permissions=[],
            )
        except AppwriteException as error:
            if error.code != 409:
                raise SecurityStoreUnavailable("security store unavailable") from None
            try:
                row = self._tables.increment_row_column(
                    self._database_id,
                    self._table_id,
                    row_id,
                    "count",
                    value=1,
                    max=self._rate_limit + 1,
                )
            except AppwriteException as increment_error:
                if increment_error.code == 409:
                    raise RateLimitExceeded(retry_after) from None
                raise SecurityStoreUnavailable("security store unavailable") from None

        count = row.data.get("count")
        if type(count) is not int:
            raise SecurityStoreUnavailable("security store unavailable")
        if count > self._rate_limit:
            raise RateLimitExceeded(retry_after)
