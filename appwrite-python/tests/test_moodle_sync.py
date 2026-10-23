import pytest

from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_sync import MoodleSyncService
from moodle_token_store import MoodleTokenStoreUnavailable
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSessionStoreUnavailable


class _Stage:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    def _run(self, user_id: str, now: int) -> object:
        self.calls.append((user_id, now))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]:
        return self._run(user_id, now)  # type: ignore[return-value]

    def discover(self, user_id: str, *, now: int) -> dict[str, object]:
        return self._run(user_id, now)  # type: ignore[return-value]

    def probe(self, user_id: str, *, now: int) -> dict[str, bool | str]:
        return self._run(user_id, now)  # type: ignore[return-value]


def test_sync_returns_all_moodle_stages_from_one_operation() -> None:
    dates = _Stage({"created": 2})
    content = _Stage({"candidate_total": 8})
    capabilities = _Stage({"direct_download_supported": True})

    result = MoodleSyncService(
        dates, content, capabilities, connection_count=lambda: 1
    ).sync("user-1", now=42)

    assert result == {
        "dates": {"created": 2},
        "content": {"candidate_total": 8},
        "capabilities": {"direct_download_supported": True},
        "saml_connections": 1,
    }
    assert dates.calls == content.calls == capabilities.calls == [("user-1", 42)]


@pytest.mark.parametrize(
    "failure",
    [
        InvalidMoodleResponse(),
        MoodleTokenStoreUnavailable(),
        MoodleUnavailable(),
        UFMGSessionStoreUnavailable(),
        TypeError(),
        ValueError(),
    ],
)
def test_sync_keeps_dates_and_content_when_capability_probe_is_optional(
    failure: Exception,
) -> None:
    result = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage(failure),
    ).sync("user-1", now=42)

    assert result["capabilities"] is None


def test_sync_preserves_reauthentication_as_a_required_failure() -> None:
    service = MoodleSyncService(
        _Stage({"created": 1}),
        _Stage({"candidate_total": 2}),
        _Stage(UFMGReauthenticationRequired()),
    )

    with pytest.raises(UFMGReauthenticationRequired):
        service.sync("user-1", now=42)
