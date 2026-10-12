from dataclasses import dataclass
from typing import Any

from ufmg_session_service import UFMGSessionService
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


@dataclass(frozen=True)
class Metadata:
    created_at: int
    expires_at: int


class Authenticator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def login(self, username: str, password: str) -> str:
        self.calls.append((username, password))
        return "private-ltpa-token"


class Store:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def save(self, user_id: str, token: str, *, now: int) -> Metadata:
        self.calls.append(("save", (user_id, token), {"now": now}))
        return Metadata(now, now + 32_400)

    def delete(self, user_id: str) -> None:
        self.calls.append(("delete", (user_id,), {}))

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        self.calls.append(("load", (user_id,), {"now": now}))
        return None


def test_connect_exchanges_credentials_and_returns_only_non_secret_metadata() -> None:
    authenticator = Authenticator()
    store = Store()
    service = UFMGSessionService(authenticator, store)

    result = service.connect(
        "firebase-user", "2025019259", "private-password", now=1_000
    )

    assert result == {"connected": True, "created_at": 1_000, "expires_at": 33_400}
    assert "private" not in repr(result)
    assert authenticator.calls == [("2025019259", "private-password")]
    assert store.calls == [
        ("save", ("firebase-user", "private-ltpa-token"), {"now": 1_000})
    ]


def test_disconnect_is_idempotent_at_the_service_boundary() -> None:
    store = Store()
    service = UFMGSessionService(Authenticator(), store)

    result = service.disconnect("firebase-user")

    assert result == {"connected": False}
    assert store.calls == [("delete", ("firebase-user",), {})]


def test_status_returns_only_non_secret_metadata() -> None:
    store = Store()
    store.load = lambda user_id, *, now: UFMGSession("private-token", 1_000, 33_400)
    service = UFMGSessionService(Authenticator(), store)

    result = service.status("firebase-user", now=2_000)

    assert result == {
        "connected": True,
        "created_at": 1_000,
        "expires_at": 33_400,
        "reauthentication_required": False,
    }
    assert "private" not in repr(result)


def test_status_distinguishes_absent_and_expired_sessions() -> None:
    store = Store()
    service = UFMGSessionService(Authenticator(), store)

    assert service.status("firebase-user", now=2_000) == {
        "connected": False,
        "reauthentication_required": False,
    }

    def expired(_user_id: str, *, now: int) -> None:
        raise UFMGReauthenticationRequired

    store.load = expired
    assert service.status("firebase-user", now=2_000) == {
        "connected": False,
        "reauthentication_required": True,
    }
