from dataclasses import dataclass

import pytest

from moodle_material import MoodleMaterialService
from moodle_structured_dates import InvalidMoodleResponse
from moodle_token_store import MoodleAuthorizationRequired, MoodleTokens


@dataclass
class _Tokens:
    value: MoodleTokens | None
    deleted: list[str]

    def load(self, _user_id: str, *, now: int) -> MoodleTokens | None:
        assert now > 0
        return self.value

    def delete(self, user_id: str) -> None:
        self.deleted.append(user_id)


class _Client:
    def __init__(self, result: list[dict[str, object]] | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def list_module_files(self, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(dict(kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _saved_tokens(term: str = "2026-2") -> MoodleTokens:
    return MoodleTokens(
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term=term,
        created_at=1,
        expires_at=99,
    )


def test_lists_files_using_only_server_side_tokens() -> None:
    tokens = _Tokens(_saved_tokens(), [])
    files = [
        {
            "name": "Plano.pdf",
            "url": "https://virtual.ufmg.br/20262/tokenpluginfile.php/private/path",
            "size": 123,
            "mime_type": "application/pdf",
        }
    ]
    client = _Client(files)

    result = MoodleMaterialService(tokens, client).list_files(
        "user-1",
        term="2026-2",
        course_id=3701,
        source_id=701,
        now=10,
    )

    assert result == {"files": files, "count": 1}
    assert client.calls == [
        {
            "webservice_token": "bbbbbbbbbbbbbbbb",
            "private_token": "aaaaaaaaaaaaaaaa",
            "term": "2026-2",
            "course_id": 3701,
            "source_id": 701,
        }
    ]
    assert "bbbbbbbbbbbbbbbb" not in repr(result)


@pytest.mark.parametrize("saved", [None, _saved_tokens("2026-1")])
def test_requires_current_term_authorization(saved: MoodleTokens | None) -> None:
    with pytest.raises(MoodleAuthorizationRequired):
        MoodleMaterialService(_Tokens(saved, []), _Client([])).list_files(
            "user-1",
            term="2026-2",
            course_id=3701,
            source_id=701,
            now=10,
        )


def test_revoked_webservice_token_is_deleted() -> None:
    tokens = _Tokens(_saved_tokens(), [])

    with pytest.raises(MoodleAuthorizationRequired):
        MoodleMaterialService(
            tokens,
            _Client(InvalidMoodleResponse("module_files_rejected")),
        ).list_files(
            "user-1",
            term="2026-2",
            course_id=3701,
            source_id=701,
            now=10,
        )

    assert tokens.deleted == ["user-1"]


def test_unexpected_moodle_shape_does_not_discard_valid_authorization() -> None:
    tokens = _Tokens(_saved_tokens(), [])
    with pytest.raises(InvalidMoodleResponse):
        MoodleMaterialService(
            tokens,
            _Client(InvalidMoodleResponse("module_file_url")),
        ).list_files(
            "user-1",
            term="2026-2",
            course_id=3701,
            source_id=701,
            now=10,
        )
    assert tokens.deleted == []
