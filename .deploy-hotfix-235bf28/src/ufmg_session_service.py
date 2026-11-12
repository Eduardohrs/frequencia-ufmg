"""Credential-minimizing orchestration for the UFMG session lifecycle."""

from typing import Any, Protocol

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Authenticator(Protocol):
    def login(self, username: str, password: str) -> str: ...


class _SessionStore(Protocol):
    def save(self, user_id: str, token: str, *, now: int) -> Any: ...

    def delete(self, user_id: str) -> None: ...

    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...


class UFMGSessionService:
    """Exchange ephemeral credentials and expose only non-secret state."""

    def __init__(self, authenticator: _Authenticator, store: _SessionStore) -> None:
        self._authenticator = authenticator
        self._store = store

    def connect(
        self,
        user_id: str,
        username: str,
        password: str,
        *,
        now: int,
    ) -> dict[str, bool | int]:
        token = self._authenticator.login(username, password)
        metadata = self._store.save(user_id, token, now=now)
        return {
            "connected": True,
            "created_at": metadata.created_at,
            "expires_at": metadata.expires_at,
        }

    def status(self, user_id: str, *, now: int) -> dict[str, bool | int]:
        try:
            session = self._store.load(user_id, now=now)
        except UFMGReauthenticationRequired:
            return {"connected": False, "reauthentication_required": True}
        if session is None:
            return {"connected": False, "reauthentication_required": False}
        return {
            "connected": True,
            "created_at": session.created_at,
            "expires_at": session.expires_at,
            "reauthentication_required": False,
        }

    def disconnect(self, user_id: str) -> dict[str, bool]:
        self._store.delete(user_id)
        return {"connected": False}
