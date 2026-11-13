import json

import pytest
from test_main import FakeContext, FakeRequest

import main as function
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from ufmg_session_store import (
    UFMGReauthenticationRequired,
    UFMGSessionStoreUnavailable,
)


def _plan(course: str, source: int, term: str = "2026-2") -> dict[str, object]:
    return {"course_id": course, "term": term, "source_id": source}


def _ok_result(course: str, source: int) -> dict[str, object]:
    return {
        "course_id": course,
        "term": "2026-2",
        "source_id": str(source),
        "plan": "created",
        "assessment_total": 1,
        "undated_assessment_total": 0,
        "dates_created": 1,
        "dates_updated": 0,
        "dates_unchanged": 0,
        "dates_removed": 0,
        "criteria_total": 1,
        "schedule_total": 10,
        "confidence": "authoritative",
    }


class _BatchService:
    def __init__(self, failures: dict[tuple[str, int], Exception] | None = None) -> None:
        self.failures = failures or {}
        self.calls: list[tuple[str, int]] = []

    def import_plan(
        self, user_id: str, *, course_id: str, term: str, source_id: int, now: int
    ) -> dict[str, object]:
        self.calls.append((course_id, source_id))
        failure = self.failures.get((course_id, source_id))
        if failure is not None:
            raise failure
        return _ok_result(course_id, source_id)


def _patch_service(monkeypatch: pytest.MonkeyPatch, service: _BatchService) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    monkeypatch.setattr(function, "_moodle_teaching_plan_batch_service", lambda *_: service)


def _post(body: object) -> FakeContext:
    return FakeContext(FakeRequest("POST", "/v1/ufmg/import/teaching-plans", body_json=body))


def test_batch_imports_all_plans_in_one_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BatchService()
    _patch_service(monkeypatch, service)
    context = _post({"plans": [_plan("course-a", 701), _plan("course-b", 702)]})

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["imported"] == 2
    assert result["body"]["failed"] == 0
    assert [r["ok"] for r in result["body"]["results"]] == [True, True]
    assert service.calls == [("course-a", 701), ("course-b", 702)]
    events = [json.loads(line)["event"] for line in context.logs]
    assert "teaching_plan_batch_started" in events
    assert "teaching_plan_batch_item_succeeded" in events
    assert "teaching_plan_batch_finished" in events


def test_batch_partial_failure_keeps_other_results(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BatchService({("course-b", 702): MoodleUnavailable()})
    _patch_service(monkeypatch, service)
    result = function.main(_post({"plans": [_plan("course-a", 701), _plan("course-b", 702)]}))

    assert result["status"] == 200
    assert result["body"]["imported"] == 1
    assert result["body"]["failed"] == 1
    assert result["body"]["results"][1] == {
        "course_id": "course-b",
        "term": "2026-2",
        "source_id": "702",
        "ok": False,
        "error": "moodle_unavailable",
    }


def test_batch_aborts_on_reauthentication(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BatchService({("course-a", 701): UFMGReauthenticationRequired()})
    _patch_service(monkeypatch, service)
    result = function.main(_post({"plans": [_plan("course-a", 701), _plan("course-b", 702)]}))

    assert result["status"] == 401
    assert result["body"] == {"error": "ufmg_reauthentication_required"}
    assert service.calls == [("course-a", 701)]


def test_batch_store_unavailable_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BatchService({("course-a", 701): UFMGSessionStoreUnavailable()})
    _patch_service(monkeypatch, service)
    result = function.main(_post({"plans": [_plan("course-a", 701)]}))
    assert result["status"] == 503
    assert result["body"] == {"error": "teaching_plan_store_unavailable"}


def test_batch_invalid_response_marks_item_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _BatchService({("course-a", 701): InvalidMoodleResponse("diario_plan_structure")})
    _patch_service(monkeypatch, service)
    result = function.main(_post({"plans": [_plan("course-a", 701)]}))
    assert result["status"] == 200
    assert result["body"]["failed"] == 1
    assert result["body"]["results"][0]["error"] == "invalid_response"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"plans": []},
        {"plans": [_plan("c", 1)] * 21},
        {"plans": [_plan("c", 1), _plan("c", 1)]},
        {"plans": [{"course_id": "c", "term": "2026-2"}]},
        {"plans": [_plan("c", 0)]},
        {"plans": [{"course_id": "c", "term": "2026-2", "source_id": 1, "extra": 1}]},
        {"plans": "nope"},
    ],
)
def test_batch_rejects_invalid_payloads(monkeypatch: pytest.MonkeyPatch, body: object) -> None:
    _patch_service(monkeypatch, _BatchService())
    result = function.main(_post(body))
    assert result["status"] == 400
    assert result["body"] == {"error": "teaching_plan_batch_rejected"}


def test_batch_route_preflight_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frequencia-ufmg-eduardo.web.app")
    context = FakeContext(
        FakeRequest(
            "OPTIONS",
            "/v1/ufmg/import/teaching-plans",
            headers={"origin": "https://frequencia-ufmg-eduardo.web.app"},
        )
    )
    result = function.main(context)
    assert result["status"] == 204
    assert result["headers"]["Access-Control-Max-Age"] == "86400"


def test_batch_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    rejected = {"status": 401, "body": {"error": "unauthorized"}}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejected))
    context = _post({"plans": [_plan("course-a", 701)]})

    result = function._moodle_teaching_plan_import_batch(context, None)

    assert result is rejected


def test_batch_factory_reuses_one_cached_session_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"firestore": object(), "sessions": object(), "client": object()}
    monkeypatch.setattr(function, "_firestore", lambda *_: values["firestore"])
    monkeypatch.setattr(function, "_ufmg_session_store", lambda *_: values["sessions"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])
    monkeypatch.setattr(function, "_course_repository", lambda *_: "courses")

    service = function._moodle_teaching_plan_batch_service({}, "user-1")

    assert isinstance(service._sessions, function.RequestCachedUFMGSessionStore)
    assert service._sessions._store is values["sessions"]
    assert service._client is values["client"]
    assert service._courses == "courses"
    assert service._plans._firestore is values["firestore"]
    assert service._dates._firestore is values["firestore"]
