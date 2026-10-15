"""Safely verify Moodle mobile download support for the current semester."""

from datetime import UTC, datetime
from typing import Protocol

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def probe_mobile_download(self, token: str, *, term: str) -> dict[str, bool]: ...


class MoodleMobileCapabilityService:
    def __init__(self, sessions: _Sessions, client: _Client) -> None:
        self._sessions = sessions
        self._client = client

    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        current = datetime.fromtimestamp(now, UTC)
        term = f"{current.year}-{'1' if current.month <= 6 else '2'}"
        try:
            capabilities = self._client.probe_mobile_download(session.token, term=term)
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        return capabilities | {"term": term}
