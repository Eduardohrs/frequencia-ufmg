from dataclasses import dataclass

import pytest

from moodle_diario_plan import MoodleDiarioPlanService
from moodle_structured_dates import DiarioPlanProbe
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


@dataclass
class _Sessions:
    session: UFMGSession | None
    deleted: list[str]

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        assert (user_id, now) == ("user-1", 123)
        return self.session

    def delete(self, user_id: str) -> None:
        self.deleted.append(user_id)


class _Client:
    def __init__(self, result: DiarioPlanProbe | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, int]] = []

    def probe_diario_plan(
        self, token: str, *, term: str, source_id: int
    ) -> DiarioPlanProbe:
        self.calls.append((token, term, source_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_probe_returns_only_safe_capability_metadata() -> None:
    client = _Client(DiarioPlanProbe(delivery="form", content_length=12_345))
    result = MoodleDiarioPlanService(
        _Sessions(UFMGSession("private-ltpa", 1, 999), []), client
    ).probe("user-1", term="2026-2", source_id=701, now=123)

    assert result == {
        "available": True,
        "delivery": "form",
        "format": "pdf",
        "content_length": 12_345,
        "term": "2026-2",
        "source_id": "701",
    }
    assert client.calls == [("private-ltpa", "2026-2", 701)]
    assert "private-ltpa" not in repr(result)


def test_probe_requires_a_saved_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleDiarioPlanService(
            _Sessions(None, []), _Client(DiarioPlanProbe("redirect", 10))
        ).probe("user-1", term="2026-2", source_id=701, now=123)


def test_probe_removes_a_session_rejected_by_ufmg() -> None:
    sessions = _Sessions(UFMGSession("expired", 1, 999), [])
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleDiarioPlanService(
            sessions, _Client(UFMGReauthenticationRequired("expired"))
        ).probe("user-1", term="2026-2", source_id=701, now=123)
    assert sessions.deleted == ["user-1"]
