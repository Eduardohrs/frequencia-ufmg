from dataclasses import dataclass
from typing import Any

import pytest

from moodle_content_discovery import MoodleContentDiscoveryService
from ufmg_session_store import UFMGReauthenticationRequired


@dataclass
class _Session:
    token: str = "private-token"


class _Sessions:
    def __init__(self, session: _Session | None | object = ...) -> None:
        self.session = _Session() if session is ... else session
        self.deleted = False

    def load(self, user_id: str, *, now: int) -> _Session | None:
        assert (user_id, now) == ("user", 123)
        return self.session

    def delete(self, user_id: str) -> None:
        assert user_id == "user"
        self.deleted = True


class _Courses:
    def list_courses(self) -> list[dict[str, Any]]:
        return [
            {"id": "course-a", "code": "DCC203", "term": "2026-2"},
            {"id": "course-b", "code": "MAT001", "term": "2026-2"},
        ]


class _Client:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def discover(
        self, token: str, *, term: str, course_codes: list[str]
    ) -> list[dict[str, object]]:
        assert token == "private-token"
        assert term == "2026-2"
        assert course_codes == ["DCC203", "MAT001"]
        if self.error:
            raise self.error
        return [
            {
                "course_code": "DCC203",
                "status": "found",
                "candidates": [
                    {
                        "source_id": "101",
                        "kind": "page",
                        "title": "Plano de ensino",
                        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                        "relevance": "teaching_plan",
                    }
                ],
            },
            {"course_code": "MAT001", "status": "empty", "candidates": []},
        ]


def test_discovery_links_candidates_to_local_courses_and_returns_counts() -> None:
    result = MoodleContentDiscoveryService(_Sessions(), _Client(), _Courses()).discover(
        "user", now=123
    )

    assert result == {
        "courses": [
            {
                "course_id": "course-a",
                "course_code": "DCC203",
                "status": "found",
                "candidates": [
                    {
                        "source_id": "101",
                        "kind": "page",
                        "title": "Plano de ensino",
                        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                        "relevance": "teaching_plan",
                    }
                ],
            },
            {
                "course_id": "course-b",
                "course_code": "MAT001",
                "status": "empty",
                "candidates": [],
            },
        ],
        "course_total": 2,
        "candidate_total": 1,
        "found": 1,
        "empty": 1,
        "unmatched": 0,
        "ambiguous": 0,
    }


def test_discovery_requires_session_and_removes_rejected_session() -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleContentDiscoveryService(_Sessions(None), _Client(), _Courses()).discover(
            "user", now=123
        )
    sessions = _Sessions()
    with pytest.raises(UFMGReauthenticationRequired):
        MoodleContentDiscoveryService(
            sessions, _Client(UFMGReauthenticationRequired()), _Courses()
        ).discover("user", now=123)
    assert sessions.deleted is True


@pytest.mark.parametrize(
    "courses",
    [
        [],
        [{"id": "", "code": "DCC203", "term": "2026-2"}],
        [
            {"id": "a", "code": "DCC203", "term": "2026-2"},
            {"id": "b", "code": "DCC203", "term": "2026-2"},
        ],
        [{"id": str(term), "code": f"DCC20{term}", "term": f"202{term}-1"} for term in (4, 5, 6)],
    ],
)
def test_discovery_rejects_invalid_local_course_sets(courses: list[dict[str, str]]) -> None:
    class Courses:
        def list_courses(self) -> list[dict[str, str]]:
            return courses

    with pytest.raises(ValueError):
        MoodleContentDiscoveryService(_Sessions(), _Client(), Courses()).discover("user", now=123)


@pytest.mark.parametrize(
    "result",
    [
        [{"course_code": "OTHER", "status": "empty", "candidates": []}],
        [
            {"course_code": "DCC203", "status": "bad", "candidates": []},
            {"course_code": "MAT001", "status": "empty", "candidates": []},
        ],
        [{"course_code": "DCC203", "status": "empty", "candidates": []}],
    ],
)
def test_discovery_rejects_invalid_client_results(result: list[dict[str, object]]) -> None:
    class Client:
        def discover(self, *_args: object, **_kwargs: object) -> list[dict[str, object]]:
            return result

    with pytest.raises(ValueError):
        MoodleContentDiscoveryService(_Sessions(), Client(), _Courses()).discover("user", now=123)
