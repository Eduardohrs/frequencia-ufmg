from dataclasses import dataclass
from typing import Any

import pytest
from appwrite.exception import AppwriteException

from quota_guard import (
    AppwriteSecurityStore,
    RateLimitExceeded,
    ReplayDetected,
    SecurityStoreUnavailable,
)


@dataclass
class Row:
    data: dict[str, Any]


class FakeTables:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def create_row(self, *args: Any, **kwargs: Any) -> Row:
        self.calls.append(("create", args, kwargs))
        row_id = args[2]
        if row_id in self.rows:
            raise AppwriteException("private conflict", 409)
        self.rows[row_id] = dict(args[3])
        return Row(self.rows[row_id])

    def increment_row_column(self, *args: Any, **kwargs: Any) -> Row:
        self.calls.append(("increment", args, kwargs))
        row_id = args[2]
        self.rows[row_id]["count"] += int(kwargs["value"])
        return Row(self.rows[row_id])


def _store(tables: Any, *, limit: int = 3) -> AppwriteSecurityStore:
    return AppwriteSecurityStore(
        tables,
        database_id="security-db",
        table_id="request-guards",
        rate_limit=limit,
        window_seconds=60,
    )


def test_consume_creates_hashed_replay_and_rate_rows_without_pii() -> None:
    tables = FakeTables()

    _store(tables).consume(
        token_digest="a" * 64,
        user_id="private-firebase-user",
        route="/v1/identity",
        expires_at=1_900,
        now=1_800,
    )

    assert len(tables.rows) == 2
    assert all(len(row_id) == 34 for row_id in tables.rows)
    assert all("private-firebase-user" not in row_id for row_id in tables.rows)
    assert {row["kind"] for row in tables.rows.values()} == {"rate", "replay"}
    assert {row["expires_at"] for row in tables.rows.values()} == {1_860, 1_900}
    assert all(call[2]["permissions"] == [] for call in tables.calls)


def test_consume_rejects_replayed_token_before_incrementing_rate() -> None:
    tables = FakeTables()
    store = _store(tables)
    request = {
        "token_digest": "b" * 64,
        "user_id": "user",
        "route": "/v1/identity",
        "expires_at": 1_900,
        "now": 1_800,
    }
    store.consume(**request)
    call_count = len(tables.calls)

    with pytest.raises(ReplayDetected):
        store.consume(**request)

    assert len(tables.calls) == call_count + 1


def test_consume_atomically_increments_shared_window_and_limits_burst() -> None:
    tables = FakeTables()
    store = _store(tables, limit=2)

    for digest in ("1" * 64, "2" * 64):
        store.consume(
            token_digest=digest,
            user_id="same-user",
            route="/v1/identity",
            expires_at=2_000,
            now=1_800,
        )

    with pytest.raises(RateLimitExceeded) as caught:
        store.consume(
            token_digest="3" * 64,
            user_id="same-user",
            route="/v1/identity",
            expires_at=2_000,
            now=1_800,
        )

    assert caught.value.retry_after == 60
    increments = [call for call in tables.calls if call[0] == "increment"]
    assert increments[-1][2] == {"value": 1, "max": 3}


def test_consume_uses_a_new_counter_after_the_fixed_window() -> None:
    tables = FakeTables()
    store = _store(tables, limit=1)

    for now, digest in ((1_800, "1" * 64), (1_860, "2" * 64)):
        store.consume(
            token_digest=digest,
            user_id="same-user",
            route="/v1/identity",
            expires_at=2_000,
            now=now,
        )

    rate_rows = [row for row in tables.rows.values() if row["kind"] == "rate"]
    assert len(rate_rows) == 2
    assert {row["expires_at"] for row in rate_rows} == {1_860, 1_920}


@pytest.mark.parametrize(
    ("database_id", "table_id", "rate_limit", "window_seconds"),
    [
        ("", "table", 1, 60),
        ("database", "", 1, 60),
        ("database", "table", 0, 60),
        ("database", "table", 1_001, 60),
        ("database", "table", 1, 0),
        ("database", "table", 1, 3_601),
    ],
)
def test_store_rejects_unsafe_configuration(
    database_id: str,
    table_id: str,
    rate_limit: int,
    window_seconds: int,
) -> None:
    with pytest.raises(ValueError):
        AppwriteSecurityStore(
            FakeTables(),
            database_id=database_id,
            table_id=table_id,
            rate_limit=rate_limit,
            window_seconds=window_seconds,
        )


@pytest.mark.parametrize(
    ("token_digest", "user_id", "route", "expires_at", "now"),
    [
        ("short", "user", "/v1/identity", 2, 1),
        ("a" * 64, "", "/v1/identity", 2, 1),
        ("a" * 64, "user", "identity", 2, 1),
        ("a" * 64, "user", "/v1/identity", 1, 1),
    ],
)
def test_consume_rejects_invalid_inputs(
    token_digest: str,
    user_id: str,
    route: str,
    expires_at: int,
    now: int,
) -> None:
    with pytest.raises(ValueError):
        _store(FakeTables()).consume(
            token_digest=token_digest,
            user_id=user_id,
            route=route,
            expires_at=expires_at,
            now=now,
        )


def test_consume_fails_closed_and_sanitizes_store_errors() -> None:
    class BrokenTables(FakeTables):
        def create_row(self, *args: Any, **kwargs: Any) -> Row:
            raise AppwriteException("private-api-key", 500)

    with pytest.raises(SecurityStoreUnavailable) as caught:
        _store(BrokenTables()).consume(
            token_digest="a" * 64,
            user_id="user",
            route="/v1/identity",
            expires_at=2,
            now=1,
        )

    assert "private-api-key" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_increment_cap_is_reported_as_rate_limit_not_store_failure() -> None:
    class CappedTables(FakeTables):
        def increment_row_column(self, *args: Any, **kwargs: Any) -> Row:
            raise AppwriteException("maximum exceeded", 409)

    tables = CappedTables()
    store = _store(tables, limit=1)
    store.consume(
        token_digest="1" * 64,
        user_id="user",
        route="/v1/identity",
        expires_at=3,
        now=1,
    )

    with pytest.raises(RateLimitExceeded):
        store.consume(
            token_digest="2" * 64,
            user_id="user",
            route="/v1/identity",
            expires_at=3,
            now=1,
        )


def test_rate_row_failure_is_sanitized() -> None:
    class BrokenRateTables(FakeTables):
        def create_row(self, *args: Any, **kwargs: Any) -> Row:
            if args[3]["kind"] == "rate":
                raise AppwriteException("private failure", 500)
            return super().create_row(*args, **kwargs)

    with pytest.raises(SecurityStoreUnavailable):
        _store(BrokenRateTables()).consume(
            token_digest="a" * 64,
            user_id="user",
            route="/v1/identity",
            expires_at=2,
            now=1,
        )


def test_increment_failure_is_sanitized() -> None:
    class BrokenIncrementTables(FakeTables):
        def increment_row_column(self, *args: Any, **kwargs: Any) -> Row:
            raise AppwriteException("private failure", 500)

    tables = BrokenIncrementTables()
    store = _store(tables)
    store.consume(
        token_digest="1" * 64,
        user_id="user",
        route="/v1/identity",
        expires_at=3,
        now=1,
    )

    with pytest.raises(SecurityStoreUnavailable):
        store.consume(
            token_digest="2" * 64,
            user_id="user",
            route="/v1/identity",
            expires_at=3,
            now=1,
        )


def test_invalid_counter_is_rejected() -> None:
    class InvalidCountTables(FakeTables):
        def create_row(self, *args: Any, **kwargs: Any) -> Row:
            row = super().create_row(*args, **kwargs)
            if args[3]["kind"] == "rate":
                row.data["count"] = "one"
            return row

    with pytest.raises(SecurityStoreUnavailable):
        _store(InvalidCountTables()).consume(
            token_digest="a" * 64,
            user_id="user",
            route="/v1/identity",
            expires_at=2,
            now=1,
        )
