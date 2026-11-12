"""Safely verify Moodle mobile download support for the current semester."""

from datetime import UTC, datetime
from typing import Protocol

from moodle_structured_dates import MoodleMobileAuthorization
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def authorize_mobile_download(
        self, token: str, *, term: str
    ) -> MoodleMobileAuthorization: ...


class _Tokens(Protocol):
    def save(
        self,
        user_id: str,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        now: int,
    ) -> object: ...

    def delete(self, user_id: str) -> None: ...


class MoodleMobileCapabilityService:
    def __init__(self, sessions: _Sessions, client: _Client, tokens: _Tokens) -> None:
        self._sessions = sessions
        self._client = client
        self._tokens = tokens

    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        current = datetime.fromtimestamp(now, UTC)
        term = f"{current.year}-{'1' if current.month <= 6 else '2'}"
        try:
            authorization = self._client.authorize_mobile_download(session.token, term=term)
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        if authorization.direct_download_supported and authorization.private_token is not None:
            self._tokens.save(
                user_id,
                webservice_token=authorization.webservice_token,
                private_token=authorization.private_token,
                term=term,
                now=now,
            )
        else:
            self._tokens.delete(user_id)
        return authorization.safe_capabilities() | {"term": term}
