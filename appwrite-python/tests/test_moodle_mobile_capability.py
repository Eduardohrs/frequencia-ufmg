from dataclasses import dataclass

import pytest

from moodle_mobile_capability import MoodleMobileCapabilityService
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
    def __init__(self, result: dict[str, bool] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def probe_mobile_download(self, token: str, *, term: str) -> dict[str, bool]:
        self.calls.append((token, term))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_probe_uses_the_current_semester_and_returns_only_safe_capabilities() -> None:
    sessions = _Sessions(UFMGSession("ltpa-secret", 1, 99), [])
    capabilities = {
        "direct_download_supported": True,
        "download_files": True,
        "private_file_access": True,
        "webservice_token_issued": True,
    }
    client = _Client(capabilities)

    result = MoodleMobileCapabilityService(sessions, client).probe(
        "user-1",
        now=1_791_936_000,
    )

    assert result == capabilities | {"term": "2026-2"}
    assert client.calls == [("ltpa-secret", "2026-2")]
    assert "ltpa-secret" not in repr(result)


def test_probe_requires_a_saved_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleMobileCapabilityService(_Sessions(None, []), _Client({})).probe(
            "user-1",
            now=1_775_000_000,
        )


def test_probe_deletes_a_session_rejected_by_the_identity_provider() -> None:
    sessions = _Sessions(UFMGSession("expired", 1, 99), [])
    client = _Client(UFMGReauthenticationRequired("expired"))

    with pytest.raises(UFMGReauthenticationRequired):
        MoodleMobileCapabilityService(sessions, client).probe(
            "user-1",
            now=1_775_000_000,
        )

    assert sessions.deleted == ["user-1"]
