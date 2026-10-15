from dataclasses import dataclass

import pytest

from moodle_mobile_capability import MoodleMobileCapabilityService
from moodle_structured_dates import MoodleMobileAuthorization
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


@dataclass
class _Sessions:
    session: UFMGSession | None
    deleted: list[str]

    def load(self, _user_id: str, *, now: int) -> UFMGSession | None:
        return self.session

    def delete(self, user_id: str) -> None:
        self.deleted.append(user_id)


class _Client:
    def __init__(self, result: MoodleMobileAuthorization | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def authorize_mobile_download(
        self, token: str, *, term: str
    ) -> MoodleMobileAuthorization:
        self.calls.append((token, term))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Tokens:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, str, int]] = []
        self.deleted: list[str] = []

    def save(
        self,
        user_id: str,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        now: int,
    ) -> None:
        self.saved.append((user_id, webservice_token, private_token, term, now))

    def delete(self, user_id: str) -> None:
        self.deleted.append(user_id)


def _authorization(*, supported: bool = True) -> MoodleMobileAuthorization:
    return MoodleMobileAuthorization(
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        direct_download_supported=supported,
        download_files=supported,
        private_file_access=supported,
    )


def test_probe_uses_the_current_semester_and_returns_only_safe_capabilities() -> None:
    sessions = _Sessions(UFMGSession("ltpa-secret", 1, 99), [])
    client = _Client(_authorization())
    tokens = _Tokens()

    result = MoodleMobileCapabilityService(sessions, client, tokens).probe(
        "user-1",
        now=1_791_936_000,
    )

    assert result == {
        "term": "2026-2",
        "direct_download_supported": True,
        "download_files": True,
        "private_file_access": True,
        "webservice_token_issued": True,
    }
    assert client.calls == [("ltpa-secret", "2026-2")]
    assert tokens.saved == [
        (
            "user-1",
            "bbbbbbbbbbbbbbbb",
            "aaaaaaaaaaaaaaaa",
            "2026-2",
            1_791_936_000,
        )
    ]
    assert "ltpa-secret" not in repr(result)
    assert "bbbbbbbbbbbbbbbb" not in repr(result)


def test_probe_requires_a_saved_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleMobileCapabilityService(
            _Sessions(None, []),
            _Client(_authorization()),
            _Tokens(),
        ).probe(
            "user-1",
            now=1_775_000_000,
        )


def test_probe_deletes_a_session_rejected_by_the_identity_provider() -> None:
    sessions = _Sessions(UFMGSession("expired", 1, 99), [])
    client = _Client(UFMGReauthenticationRequired("expired"))

    with pytest.raises(UFMGReauthenticationRequired):
        MoodleMobileCapabilityService(sessions, client, _Tokens()).probe(
            "user-1",
            now=1_775_000_000,
        )

    assert sessions.deleted == ["user-1"]


def test_probe_does_not_persist_credentials_when_download_is_unsupported() -> None:
    tokens = _Tokens()

    result = MoodleMobileCapabilityService(
        _Sessions(UFMGSession("ltpa-secret", 1, 99), []),
        _Client(_authorization(supported=False)),
        tokens,
    ).probe("user-1", now=1_791_936_000)

    assert result["direct_download_supported"] is False
    assert tokens.saved == []
    assert tokens.deleted == ["user-1"]
