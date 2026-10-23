"""Coordinate one Moodle synchronization over a shared authenticated client."""

from collections.abc import Callable
from typing import Protocol

from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleTokenStoreUnavailable
from ufmg_session_store import UFMGSessionStoreUnavailable


class _Dates(Protocol):
    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]: ...


class _Content(Protocol):
    def discover(self, user_id: str, *, now: int) -> dict[str, object]: ...


class _Capabilities(Protocol):
    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]: ...


class MoodleSyncService:
    """Run Moodle stages together so their client can reuse the SAML session."""

    def __init__(
        self,
        dates: _Dates,
        content: _Content,
        capabilities: _Capabilities,
        *,
        connection_count: Callable[[], int] = lambda: 0,
    ) -> None:
        self._dates = dates
        self._content = content
        self._capabilities = capabilities
        self._connection_count = connection_count

    def sync(self, user_id: str, *, now: int) -> dict[str, object]:
        dates = self._dates.import_dates(user_id, now=now)
        content = self._content.discover(user_id, now=now)
        try:
            capabilities: dict[str, bool | str] | None = self._capabilities.probe(
                user_id, now=now
            )
        except (
            InvalidMoodleResponse,
            MoodleTokenStoreUnavailable,
            MoodleUnavailable,
            UFMGSessionStoreUnavailable,
            TypeError,
            ValueError,
        ):
            capabilities = None
        return {
            "dates": dates,
            "content": content,
            "capabilities": capabilities,
            "saml_connections": self._connection_count(),
        }
