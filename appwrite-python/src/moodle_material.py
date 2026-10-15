"""Resolve Moodle material files without proxying or retaining file bytes."""

from typing import Protocol

from moodle_structured_dates import InvalidMoodleResponse
from moodle_token_store import MoodleAuthorizationRequired, MoodleTokens


class _Tokens(Protocol):
    def load(self, user_id: str, *, now: int) -> MoodleTokens | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def list_module_files(
        self,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        course_id: int,
        source_id: int,
    ) -> list[dict[str, object]]: ...


class MoodleMaterialService:
    def __init__(self, tokens: _Tokens, client: _Client) -> None:
        self._tokens = tokens
        self._client = client

    def list_files(
        self,
        user_id: str,
        *,
        term: str,
        course_id: int,
        source_id: int,
        now: int,
    ) -> dict[str, object]:
        tokens = self._tokens.load(user_id, now=now)
        if tokens is None or tokens.term != term:
            raise MoodleAuthorizationRequired("Moodle authorization required")
        try:
            files = self._client.list_module_files(
                webservice_token=tokens.webservice_token,
                private_token=tokens.private_token,
                term=term,
                course_id=course_id,
                source_id=source_id,
            )
        except InvalidMoodleResponse as error:
            if error.reason == "module_files_rejected":
                self._tokens.delete(user_id)
                raise MoodleAuthorizationRequired("Moodle authorization required") from None
            raise
        return {"files": files, "count": len(files)}
