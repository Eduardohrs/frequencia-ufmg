"""Validate access to a structured UFMG Diario de Classe plan without retaining it."""

from typing import Protocol

from moodle_structured_dates import DiarioPlanProbe
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def probe_diario_plan(
        self, token: str, *, term: str, source_id: int
    ) -> DiarioPlanProbe: ...


class MoodleDiarioPlanService:
    def __init__(self, sessions: _Sessions, client: _Client) -> None:
        self._sessions = sessions
        self._client = client

    def probe(
        self,
        user_id: str,
        *,
        term: str,
        source_id: int,
        now: int,
    ) -> dict[str, object]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        try:
            result = self._client.probe_diario_plan(
                session.token,
                term=term,
                source_id=source_id,
            )
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise
        return result.safe_result() | {"term": term, "source_id": str(source_id)}
