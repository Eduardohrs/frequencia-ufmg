import json
from typing import Any

import pytest
from test_main import FakeContext, FakeRequest

import main as function
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreRequestRejected,
    FirestoreUnavailable,
)
from overview_repository import OverviewTooLarge
from schedule_service import InvalidSchedule


class Repository:
    failure: Exception | None = None

    def load(self) -> list[dict[str, Any]]:
        if self.failure is not None:
            raise self.failure
        return [
            {
                "course": {"id": "poo"},
                "sessions": [{"id": "session-1"}, {"id": "session-2"}],
            }
        ]


def _enable(monkeypatch: pytest.MonkeyPatch, repository: Repository) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(function, "_overview_repository", lambda *_args: repository)
    monkeypatch.setenv("ENABLE_OVERVIEW_READS", "true")


def test_overview_returns_one_bounded_snapshot_and_count_only_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, Repository())
    context = FakeContext(FakeRequest("GET", "/v1/overview"))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["items"][0]["course"] == {"id": "poo"}
    assert json.loads(context.logs[0]) == {
        "event": "overview_load_succeeded",
        "course_count": 1,
        "session_count": 2,
    }


def test_overview_switch_fails_closed_after_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "user", None

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.delenv("ENABLE_OVERVIEW_READS", raising=False)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/overview")))

    assert result["status"] == 503
    assert result["body"] == {"error": "overview_reads_disabled"}
    assert routes == ["/v1/overview"]


def test_overview_returns_authentication_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("GET", "/v1/overview"))) is rejection


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (OverviewTooLarge(), 409, "overview_too_large"),
        (InvalidSchedule(), 500, "overview_data_invalid"),
        (FirestoreRequestRejected(), 500, "overview_data_invalid"),
        (FirestoreAccessDenied(), 403, "overview_access_denied"),
        (FirestoreUnavailable(), 503, "overview_store_unavailable"),
    ],
)
def test_overview_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Repository()
    repository.failure = failure
    _enable(monkeypatch, repository)
    context = FakeContext(FakeRequest("GET", "/v1/overview"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    assert json.loads(context.errors[0]) == {"event": error}


def test_overview_repository_uses_the_shared_firestore_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object()
    monkeypatch.setattr(function, "_firestore", lambda *_args: client)
    monkeypatch.setattr(
        function,
        "AcademicOverviewRepository",
        lambda value: ("overview", value),
    )

    assert function._overview_repository({}, "user") == ("overview", client)
