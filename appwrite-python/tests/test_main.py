import json
from base64 import b64encode
from dataclasses import dataclass, field
from typing import Any

import pytest

import main as function
from academic_date_repository import InvalidAcademicDate
from course_repository import DuplicateCourseCode
from course_service import InvalidCourse
from firebase_app_check import FirebaseAppIdentity, InvalidAppCheck
from firebase_identity import InvalidIdentity
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreUnavailable,
)
from moodle_material_catalog_repository import InvalidMoodleMaterialCatalog
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleAuthorizationRequired, MoodleTokenStoreUnavailable
from quota_guard import RateLimitExceeded, ReplayDetected, SecurityStoreUnavailable
from schedule_repository import DestructiveScheduleChange
from schedule_service import InvalidSchedule, ScheduleOverlap
from teaching_plan_repository import InvalidTeachingPlan
from ufmg_auth import InvalidUFMGCredentials, UFMGAuthenticationUnavailable
from ufmg_course_import import (
    InvalidUFMGEnrollmentResponse,
    UFMGEnrollmentUnavailable,
)
from ufmg_session_store import (
    InvalidUFMGSession,
    UFMGReauthenticationRequired,
    UFMGSessionStoreUnavailable,
)


@dataclass
class FakeRequest:
    method: str
    path: str
    body_json: dict[str, Any] = field(default_factory=dict)
    body_binary: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class FakeResponse:
    def json(
        self,
        body: dict[str, Any],
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {"body": body, "headers": headers or {}, "status": status}


@dataclass
class FakeContext:
    req: FakeRequest
    res: FakeResponse = field(default_factory=FakeResponse)
    logs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.logs.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


def test_unknown_route_returns_not_found() -> None:
    context = FakeContext(FakeRequest("GET", "/unknown"))

    result = function.main(context)
    assert result["body"] == {"error": "not_found"}
    assert result["status"] == 404


def test_moodle_sync_route_returns_one_bounded_combined_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    class Service:
        def sync(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "firebase-user"
            assert now > 0
            return {
                "dates": {
                    "total": 3,
                    "matched": 2,
                    "unmatched": 1,
                    "created": 1,
                    "updated": 1,
                    "unchanged": 0,
                },
                "content": {
                    "courses": [{"private": "not returned"}],
                    "course_total": 2,
                    "candidate_total": 8,
                    "metaturma_candidate_total": 3,
                    "found": 1,
                    "empty": 1,
                    "unmatched": 0,
                    "ambiguous": 0,
                    "catalog": {"writes": 1},
                },
                "capabilities": {
                    "term": "2026-2",
                    "direct_download_supported": True,
                    "download_files": True,
                    "private_file_access": True,
                    "webservice_token_issued": False,
                },
                "saml_connections": 1,
            }

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_moodle_sync_service", lambda *_args: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle"))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["dates"]["total"] == 3
    assert result["body"]["content"] == {
        "course_total": 2,
        "candidate_total": 8,
        "metaturma_candidate_total": 3,
        "found": 1,
        "empty": 1,
        "unmatched": 0,
        "ambiguous": 0,
    }
    assert result["body"]["capabilities"]["webservice_token_issued"] is False
    assert "not returned" not in json.dumps(result)
    assert routes == ["/v1/ufmg/sync/moodle/post"]
    sync_log = next(
        json.loads(item)
        for item in context.logs
        if json.loads(item)["event"] == "moodle_sync_succeeded"
    )
    assert sync_log["saml_connections"] == 1


def test_moodle_sync_route_preserves_an_optional_capability_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Service:
        def sync(self, _user_id: str, *, now: int) -> dict[str, object]:
            assert now > 0
            return {
                "dates": {"total": 0},
                "content": {
                    "course_total": 0,
                    "candidate_total": 0,
                    "metaturma_candidate_total": 0,
                    "found": 0,
                    "empty": 0,
                    "unmatched": 0,
                    "ambiguous": 0,
                },
                "capabilities": None,
                "saml_connections": 0,
            }

    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(function, "_moodle_sync_service", lambda *_args: Service())

    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle")))

    assert result["body"]["capabilities"] is None


def test_moodle_sync_factory_shares_one_client_across_all_remote_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = object()
    client = object()
    courses = object()
    firestore = object()
    catalog = object()
    tokens = object()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: sessions)
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: client)
    monkeypatch.setattr(function, "_course_repository", lambda _headers, _user: courses)
    monkeypatch.setattr(function, "_firestore", lambda _headers, _user: firestore)
    monkeypatch.setattr(
        function,
        "_moodle_material_catalog_repository",
        lambda _headers, _user: catalog,
    )
    monkeypatch.setattr(function, "_moodle_token_store", lambda _headers: tokens)

    service = function._moodle_sync_service({}, "user-1")

    assert service._dates._sessions is sessions
    assert service._dates._client is client
    assert service._dates._courses is courses
    assert service._dates._dates._firestore is firestore
    assert service._content._sessions is sessions
    assert service._content._client is client
    assert service._content._courses is courses
    assert service._content._catalog is catalog
    assert service._capabilities._sessions is sessions
    assert service._capabilities._client is client
    assert service._capabilities._tokens is tokens


def test_moodle_sync_route_rejects_authentication_and_nonempty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))
    assert (
        function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle")))
        is rejection
    )

    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle", body_json={"bad": True}))
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_sync_rejected"}


@pytest.mark.parametrize(
    ("failure", "error", "status"),
    [
        (UFMGReauthenticationRequired(), "ufmg_reauthentication_required", 401),
        (MoodleUnavailable(), "moodle_unavailable", 503),
        (InvalidMoodleResponse("course_list_json"), "moodle_response_invalid", 502),
        (UFMGSessionStoreUnavailable(), "ufmg_session_store_unavailable", 503),
        (FirestoreAccessDenied(), "course_access_denied", 403),
        (FirestoreUnavailable(), "course_store_unavailable", 503),
        (InvalidAcademicDate(), "moodle_sync_rejected", 502),
        (InvalidCourse(), "moodle_sync_rejected", 502),
        (InvalidMoodleMaterialCatalog(), "moodle_sync_rejected", 502),
        (FirestoreRequestRejected(), "moodle_sync_rejected", 502),
        (TypeError(), "moodle_sync_rejected", 502),
        (ValueError(), "moodle_sync_rejected", 502),
    ],
)
def test_moodle_sync_route_maps_safe_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    error: str,
    status: int,
) -> None:
    class Service:
        def sync(self, _user_id: str, *, now: int) -> dict[str, object]:
            assert now > 0
            raise failure

    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(function, "_moodle_sync_service", lambda *_args: Service())

    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle")))

    assert result["status"] == status
    assert result["body"]["error"] == error


def test_ufmg_session_routes_are_authenticated_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    class Service:
        def status(self, user_id: str, *, now: int) -> dict[str, Any]:
            assert user_id == "firebase-user"
            assert now > 0
            return {"connected": False, "reauthentication_required": False}

        def connect(
            self,
            user_id: str,
            username: str,
            password: str,
            *,
            now: int,
        ) -> dict[str, Any]:
            assert (user_id, username, password) == (
                "firebase-user",
                "2025019259",
                "private-password",
            )
            return {"connected": True, "created_at": now, "expires_at": now + 32_400}

        def disconnect(self, user_id: str) -> dict[str, bool]:
            assert user_id == "firebase-user"
            return {"connected": False}

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_ufmg_session_service", lambda *_args: Service())
    deleted_moodle_tokens: list[str] = []

    class MoodleTokens:
        def delete(self, user_id: str) -> None:
            deleted_moodle_tokens.append(user_id)

    monkeypatch.setattr(function, "_moodle_token_store", lambda *_args: MoodleTokens())
    status = FakeContext(FakeRequest("GET", "/v1/ufmg/session"))
    connected = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/session",
            body_json={"username": "2025019259", "password": "private-password"},
        )
    )
    disconnected = FakeContext(FakeRequest("DELETE", "/v1/ufmg/session"))

    assert function.main(status)["body"]["connected"] is False
    assert function.main(connected)["body"]["connected"] is True
    assert function.main(disconnected)["body"] == {"connected": False}
    assert deleted_moodle_tokens == ["firebase-user"]
    assert routes == [
        "/v1/ufmg/session/get",
        "/v1/ufmg/session/post",
        "/v1/ufmg/session/delete",
    ]
    emitted = "".join(status.logs + connected.logs + disconnected.logs)
    assert "private-password" not in emitted
    assert "2025019259" not in emitted
    assert [
        json.loads(item)["event"]
        for item in status.logs + connected.logs + disconnected.logs
        if json.loads(item)["event"] != "request_completed"
    ] == [
        "ufmg_session_status_succeeded",
        "ufmg_session_connect_succeeded",
        "ufmg_session_disconnect_succeeded",
    ]


def test_ufmg_session_route_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("GET", "/v1/ufmg/session"))) is rejection


def test_ufmg_session_service_builds_only_with_complete_secure_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "APPWRITE_FUNCTION_API_ENDPOINT",
        "APPWRITE_FUNCTION_PROJECT_ID",
        "SECURITY_DATABASE_ID",
        "UFMG_SESSION_TABLE_ID",
        "UFMG_SESSION_ACTIVE_KEY_VERSION",
        "UFMG_SESSION_ENCRYPTION_KEY_V1",
        "UFMG_SESSION_INDEX_KEY",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(UFMGSessionStoreUnavailable):
        function._ufmg_session_service({})

    monkeypatch.setenv("APPWRITE_FUNCTION_API_ENDPOINT", "https://appwrite.example/v1")
    monkeypatch.setenv("APPWRITE_FUNCTION_PROJECT_ID", "project")
    monkeypatch.setenv("SECURITY_DATABASE_ID", "database")
    monkeypatch.setenv("UFMG_SESSION_TABLE_ID", "sessions")
    monkeypatch.setenv("UFMG_SESSION_ACTIVE_KEY_VERSION", "1")
    monkeypatch.setenv("UFMG_SESSION_ENCRYPTION_KEY_V1", b64encode(b"e" * 32).decode())
    monkeypatch.setenv("UFMG_SESSION_INDEX_KEY", b64encode(b"i" * 32).decode())

    service = function._ufmg_session_service({"x-appwrite-key": "runtime-key"})

    assert service.__class__.__name__ == "UFMGSessionService"


@pytest.mark.parametrize(
    ("failure", "method", "status", "error"),
    [
        (
            InvalidUFMGCredentials("login_response_rejected"),
            "POST",
            401,
            "ufmg_credentials_invalid",
        ),
        (
            UFMGAuthenticationUnavailable("portal_entry_timeout"),
            "POST",
            503,
            "ufmg_authentication_unavailable",
        ),
        (UFMGSessionStoreUnavailable(), "GET", 503, "ufmg_session_store_unavailable"),
        (InvalidUFMGSession(), "DELETE", 400, "ufmg_session_rejected"),
        (ValueError(), "POST", 503, "ufmg_session_configuration_invalid"),
    ],
)
def test_ufmg_session_routes_map_failures_without_leaking_input(
    failure: Exception,
    method: str,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Service:
        def status(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

        def connect(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

        def disconnect(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_ufmg_session_service", lambda *_args: Service())
    context = FakeContext(
        FakeRequest(
            method,
            "/v1/ufmg/session",
            body_json={"username": "private-user", "password": "private-password"},
        )
    )

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    emitted = "".join(context.logs + context.errors)
    expected_log = {"event": error}
    if isinstance(failure, InvalidUFMGCredentials):
        expected_log["reason"] = "login_response_rejected"
    if isinstance(failure, UFMGAuthenticationUnavailable):
        expected_log["reason"] = "portal_entry_timeout"
    assert json.loads(context.errors[0]) == expected_log
    assert "private" not in emitted


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"username": "student"},
        {"username": "student", "password": "secret", "extra": True},
        {"username": 1, "password": "secret"},
    ],
)
def test_ufmg_connect_rejects_malformed_payload(
    body: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(
        function,
        "_ufmg_session_service",
        lambda *_args: pytest.fail("must reject before service"),
    )

    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/session", body_json=body)))

    assert result["status"] == 400
    assert result["body"] == {"error": "ufmg_session_rejected"}


def test_ufmg_course_import_route_is_authenticated_and_logs_only_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    class Service:
        def import_courses(self, user_id: str, *, now: int) -> dict[str, int]:
            assert user_id == "firebase-user"
            assert now > 0
            return {"created": 2, "existing": 3, "total": 5}

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_ufmg_course_import_service", lambda *_args: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/import/courses"))

    result = function.main(context)

    assert result["body"] == {"created": 2, "existing": 3, "total": 5}
    assert routes == ["/v1/ufmg/import/courses/post"]
    assert json.loads(context.logs[0]) == {
        "created": 2,
        "event": "ufmg_course_import_succeeded",
        "existing": 3,
        "total": 5,
    }


def test_ufmg_schedule_import_route_is_authenticated_and_logs_only_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    summary = {
        "total": 5,
        "updated": 2,
        "unchanged": 1,
        "conflicts": 1,
        "missing_courses": 1,
        "meetings_imported": 3,
        "date_mismatches": 2,
        "meeting_mismatches": 1,
        "meeting_upserts": 2,
        "meeting_deletes": 0,
        "session_upserts": 18,
        "session_deletes": 0,
    }

    class Service:
        def import_schedules(self, user_id: str, *, now: int) -> dict[str, int]:
            assert user_id == "firebase-user"
            assert now > 0
            return summary

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_ufmg_schedule_import_service", lambda *_args: Service())
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/import/schedules"))

    result = function.main(context)

    assert result["body"] == {
        key: summary[key]
        for key in (
            "total",
            "updated",
            "unchanged",
            "conflicts",
            "missing_courses",
            "meetings_imported",
        )
    }
    assert routes == ["/v1/ufmg/import/schedules/post"]
    assert json.loads(context.logs[0]) == {
        "event": "ufmg_schedule_import_succeeded",
        **summary,
    }


def test_ufmg_sync_route_returns_the_bounded_combined_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    result_payload = {
        "courses": {"created": 1, "existing": 4, "total": 5},
        "schedules": {
            "total": 5,
            "updated": 1,
            "unchanged": 3,
            "conflicts": 1,
            "missing_courses": 0,
            "meetings_imported": 2,
        },
        "dates": {
            "total": 3,
            "matched": 2,
            "unmatched": 1,
            "created": 1,
            "updated": 0,
            "unchanged": 1,
        },
        "checked_at": "2026-10-13T12:00:00Z",
        "next_automatic_sync_at": "2026-12-06T00:00:00Z",
    }

    class Service:
        def sync(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "firebase-user"
            assert now > 0
            return result_payload

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_ufmg_sync_service", lambda *_args: Service())
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/sync"))

    response = function.main(context)

    assert response["body"] == result_payload
    assert routes == ["/v1/ufmg/sync/post"]
    assert json.loads(context.logs[0]) == {
        "course_created": 1,
        "course_total": 5,
        "date_created": 1,
        "date_matched": 2,
        "date_total": 3,
        "date_unmatched": 1,
        "event": "ufmg_sync_succeeded",
        "schedule_conflicts": 1,
        "schedule_total": 5,
        "schedule_updated": 1,
    }


def test_ufmg_siga_sync_route_preserves_the_legacy_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []
    result_payload = {
        "courses": {"created": 1, "existing": 4, "total": 5},
        "schedules": {
            "total": 5,
            "updated": 1,
            "unchanged": 3,
            "conflicts": 1,
            "missing_courses": 0,
            "meetings_imported": 2,
        },
        "checked_at": "2026-10-13T12:00:00Z",
        "next_automatic_sync_at": "2026-12-06T00:00:00Z",
    }

    class Service:
        def sync_siga(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "firebase-user"
            assert now > 0
            return result_payload

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_ufmg_sync_service", lambda *_args: Service())
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/sync/siga"))

    response = function.main(context)

    assert response["body"] == result_payload
    assert routes == ["/v1/ufmg/sync/siga/post"]
    assert json.loads(context.logs[0]) == {
        "course_created": 1,
        "course_total": 5,
        "event": "ufmg_siga_sync_succeeded",
        "schedule_conflicts": 1,
        "schedule_total": 5,
        "schedule_updated": 1,
    }


def test_moodle_date_import_route_is_authenticated_and_logs_only_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []
    summary = {
        "total": 4,
        "matched": 3,
        "unmatched": 1,
        "created": 2,
        "updated": 1,
        "unchanged": 0,
    }

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "firebase-user", None

    class Service:
        def import_dates(self, user_id: str, *, now: int) -> dict[str, int]:
            assert user_id == "firebase-user"
            assert now > 0
            return summary

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.setattr(function, "_moodle_date_import_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/import/dates"))

    response = function.main(context)

    assert response["body"] == summary
    assert routes == ["/v1/ufmg/import/dates/post"]
    assert json.loads(context.logs[0]) == {
        "event": "moodle_date_import_succeeded",
        **summary,
    }


def test_moodle_content_discovery_returns_candidates_but_logs_only_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    result = {
        "courses": [
            {
                "course_id": "private-id",
                "course_code": "DCC203",
                "term": "2026-2",
                "moodle_course_id": "3701",
                "status": "found",
                "candidates": [
                    {
                        "source_id": "101",
                        "moodle_course_id": "4999",
                        "kind": "page",
                        "title": "Plano de ensino",
                        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                        "relevance": "teaching_plan",
                        "origin": "metaturma",
                    }
                ],
            }
        ],
        "course_total": 1,
        "candidate_total": 1,
        "metaturma_candidate_total": 1,
        "found": 1,
        "empty": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "catalog": {
            "created": 1,
            "updated": 0,
            "unchanged": 0,
            "removed": 0,
            "writes": 1,
        },
    }

    class Service:
        def discover(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "user" and now > 0
            return result

    monkeypatch.setattr(function, "_moodle_content_discovery_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/discover/content"))

    body = function.main(context)["body"]
    expected = json.loads(json.dumps(result))
    expected.pop("catalog")
    expected["courses"][0]["candidates"][0].pop("moodle_course_id")
    assert body == expected
    assert "moodle_course_id" not in body["courses"][0]["candidates"][0]
    assert json.loads(context.logs[0]) == {
        "event": "moodle_content_discovery_succeeded",
        "course_total": 1,
        "candidate_total": 1,
        "found": 1,
        "empty": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "metaturma_candidates": 1,
        "catalog_created": 1,
        "catalog_updated": 0,
        "catalog_unchanged": 0,
        "catalog_removed": 0,
        "catalog_writes": 1,
    }


def test_moodle_material_catalog_returns_persisted_metadata_and_logs_only_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    payload = {
        "courses": [
            {
                "course_id": "private-id",
                "course_code": "DCC203",
                "term": "2026-2",
                "moodle_course_id": "3701",
                "status": "found",
                "candidates": [
                    {
                        "source_id": "101",
                        "moodle_course_id": "3701",
                        "kind": "page",
                        "title": "Plano de ensino",
                        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                        "relevance": "teaching_plan",
                        "origin": "canonical",
                    }
                ],
            }
        ],
        "course_total": 1,
        "candidate_total": 1,
        "metaturma_candidate_total": 0,
        "found": 1,
        "empty": 0,
        "unmatched": 0,
        "ambiguous": 0,
    }

    class Service:
        def list_catalog(self) -> dict[str, object]:
            return payload

    monkeypatch.setattr(function, "_moodle_material_catalog_service", lambda *_: Service())
    context = FakeContext(FakeRequest("GET", "/v1/moodle/materials"))

    assert function.main(context)["body"] == payload
    assert json.loads(context.logs[0]) == {
        "event": "moodle_material_catalog_listed",
        "course_total": 1,
        "candidate_total": 1,
        "metaturma_candidates": 0,
    }
    assert "Plano de ensino" not in json.dumps(context.logs)


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (ValueError(), 502, "moodle_material_catalog_rejected"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
    ],
)
def test_moodle_material_catalog_rejects_auth_and_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("GET", "/v1/moodle/materials"))) is rejection

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Service:
        def list_catalog(self) -> None:
            raise failure

    monkeypatch.setattr(function, "_moodle_material_catalog_service", lambda *_: Service())
    response = function.main(FakeContext(FakeRequest("GET", "/v1/moodle/materials")))
    assert response["status"] == status
    assert response["body"] == {"error": error}


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse(), 502, "moodle_response_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
        (InvalidCourse(), 502, "moodle_content_discovery_rejected"),
        (FirestoreRequestRejected(), 502, "moodle_content_discovery_rejected"),
        (TypeError(), 502, "moodle_content_discovery_rejected"),
        (ValueError(), 502, "moodle_content_discovery_rejected"),
    ],
)
def test_moodle_content_discovery_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Service:
        def discover(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_moodle_content_discovery_service", lambda *_: Service())
    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/discover/content")))
    assert result["status"] == status
    assert result["body"] == {"error": error}


def test_moodle_content_discovery_logs_safe_failure_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Service:
        def discover(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("private upstream detail")

    monkeypatch.setattr(function, "_moodle_content_discovery_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/discover/content"))

    function.main(context)

    assert json.loads(context.errors[0]) == {
        "event": "moodle_content_discovery_rejected",
        "reason": "value_error",
    }
    assert "private upstream detail" not in "".join(context.errors)


def test_moodle_content_discovery_rejects_auth_and_nonempty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/discover/content"))) is rejection
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    result = function.main(
        FakeContext(
            FakeRequest("POST", "/v1/ufmg/discover/content", body_json={"unexpected": True})
        )
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_content_discovery_rejected"}


def test_moodle_mobile_capability_route_returns_and_logs_only_safe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        function,
        "_authentication",
        lambda *_: ("user-1", None),
    )

    class Service:
        def probe(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "user-1"
            assert now > 0
            return {
                "term": "2026-2",
                "direct_download_supported": True,
                "download_files": True,
                "private_file_access": True,
                "webservice_token_issued": True,
            }

    monkeypatch.setattr(function, "_moodle_mobile_capability_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/capabilities"))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["direct_download_supported"] is True
    event = json.loads(context.logs[0])
    assert event == {
        "direct_download_supported": True,
        "download_files": True,
        "event": "moodle_mobile_capability_succeeded",
        "private_file_access": True,
        "term": "2026-2",
        "webservice_token_issued": True,
    }
    assert "ltpa-secret" not in json.dumps(result)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse("mobile_callback_site"), 502, "moodle_response_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (ValueError(), 502, "moodle_mobile_capability_rejected"),
    ],
)
def test_moodle_mobile_capability_route_sanitizes_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def probe(self, _user_id: str, *, now: int) -> dict[str, object]:
            assert now > 0
            raise error

    monkeypatch.setattr(function, "_moodle_mobile_capability_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/capabilities"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": code}


def test_moodle_mobile_capability_rejects_auth_and_nonempty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert (
        function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/capabilities")))
        is rejection
    )

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/ufmg/moodle/capabilities",
                body_json={"unexpected": True},
            )
        )
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_mobile_capability_rejected"}


def test_moodle_mobile_capability_factory_uses_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"sessions": object(), "client": object(), "tokens": object()}
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: values["sessions"])
    monkeypatch.setattr(function, "_moodle_token_store", lambda _headers: values["tokens"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])

    service = function._moodle_mobile_capability_service({})

    assert service._sessions is values["sessions"]
    assert service._client is values["client"]
    assert service._tokens is values["tokens"]


def test_moodle_material_files_route_returns_only_direct_file_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def list_files(self, user_id: str, **kwargs: object) -> dict[str, object]:
            assert user_id == "user-1"
            assert kwargs["term"] == "2026-2"
            assert kwargs["course_id"] == 3701
            assert kwargs["source_id"] == 701
            assert isinstance(kwargs["now"], int)
            return {
                "files": [
                    {
                        "name": "Plano.pdf",
                        "url": (
                            "https://virtual.ufmg.br/20262/tokenpluginfile.php/"
                            "aaaaaaaaaaaaaaaa/path"
                        ),
                        "size": 123,
                        "mime_type": "application/pdf",
                    }
                ],
                "count": 1,
            }

    monkeypatch.setattr(function, "_moodle_material_service", lambda *_: Service())
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/moodle/material-files",
            body_json={"term": "2026-2", "course_id": 3701, "source_id": 701},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["count"] == 1
    event = json.loads(context.logs[0])
    assert event == {"event": "moodle_material_files_succeeded", "file_count": 1}
    assert "aaaaaaaaaaaaaaaa" not in json.dumps(context.logs)


def test_moodle_material_files_route_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert (
        function.main(
            FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/material-files"))
        )
        is rejection
    )


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (MoodleAuthorizationRequired(), 401, "moodle_authorization_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse("module_file_url"), 502, "moodle_response_invalid"),
        (MoodleTokenStoreUnavailable(), 503, "moodle_token_store_unavailable"),
        (ValueError(), 400, "moodle_material_request_rejected"),
    ],
)
def test_moodle_material_files_route_sanitizes_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def list_files(self, *_args: object, **_kwargs: object) -> None:
            raise error

    monkeypatch.setattr(function, "_moodle_material_service", lambda *_: Service())
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/ufmg/moodle/material-files",
                body_json={"term": "2026-2", "course_id": 3701, "source_id": 701},
            )
        )
    )
    assert result["status"] == status
    assert result["body"] == {"error": code}


def test_moodle_diario_plan_route_returns_only_safe_probe_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def probe(self, user_id: str, **values: object) -> dict[str, object]:
            assert user_id == "user-1"
            assert values["term"] == "2026-2"
            assert values["source_id"] == 701
            assert isinstance(values["now"], int)
            return {
                "available": True,
                "delivery": "form",
                "format": "pdf",
                "content_length": 12_345,
                "term": "2026-2",
                "source_id": "701",
            }

    monkeypatch.setattr(function, "_moodle_diario_plan_service", lambda *_: Service())
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/moodle/diario-plan",
            body_json={"term": "2026-2", "source_id": 701},
        )
    )
    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["available"] is True
    assert (
        '{"content_length":12345,"delivery":"form",'
        '"event":"moodle_diario_plan_succeeded","format":"pdf"}'
    ) in context.logs


def test_moodle_diario_plan_route_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = {"status": 401, "body": {"error": "identity_invalid"}}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejected))

    result = function._moodle_diario_plan(
        FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/diario-plan")),
        None,
    )

    assert result is rejected


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse("diario_response_pdf"), 502, "moodle_response_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (ValueError(), 400, "moodle_diario_plan_rejected"),
    ],
)
def test_moodle_diario_plan_route_sanitizes_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def probe(self, *_args: object, **_kwargs: object) -> None:
            raise error

    monkeypatch.setattr(function, "_moodle_diario_plan_service", lambda *_: Service())
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/ufmg/moodle/diario-plan",
                body_json={"term": "2026-2", "source_id": 701},
            )
        )
    )
    assert result["status"] == status
    assert result["body"] == {"error": code}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"term": "20262", "source_id": 701},
        {"term": "2026-2", "source_id": "701"},
        {"term": "2026-2", "source_id": 0},
        {"term": "2026-2", "source_id": 701, "unexpected": True},
    ],
)
def test_moodle_diario_plan_route_rejects_invalid_bodies(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/diario-plan", body_json=body))
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_diario_plan_rejected"}


def test_moodle_diario_plan_factory_uses_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"sessions": object(), "client": object()}
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _: values["sessions"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])

    service = function._moodle_diario_plan_service({})

    assert service._sessions is values["sessions"]
    assert service._client is values["client"]


def test_teaching_plan_import_route_returns_sanitized_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def import_plan(self, user_id: str, **values: object) -> dict[str, object]:
            assert user_id == "user-1"
            assert values["course_id"] == "course-a"
            assert values["term"] == "2026-2"
            assert values["source_id"] == 701
            return {
                "course_id": "course-a",
                "term": "2026-2",
                "source_id": "701",
                "plan": "created",
                "assessment_total": 2,
                "dates_created": 2,
                "dates_updated": 0,
                "dates_unchanged": 0,
                "dates_removed": 0,
                "criteria_total": 2,
                "schedule_total": 30,
                "confidence": "authoritative",
            }

    monkeypatch.setattr(function, "_moodle_teaching_plan_import_service", lambda *_: Service())
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/import/teaching-plan",
            body_json={"course_id": "course-a", "term": "2026-2", "source_id": 701},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["assessment_total"] == 2
    assert '"event":"teaching_plan_import_succeeded"' in context.logs[0]


def test_teaching_plan_import_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = {"status": 401, "body": {"error": "identity_invalid"}}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejected))
    result = function._moodle_teaching_plan_import(
        FakeContext(FakeRequest("POST", "/v1/ufmg/import/teaching-plan")), None
    )
    assert result is rejected


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse("diario_plan_structure"), 502, "moodle_response_invalid"),
        (InvalidTeachingPlan(), 400, "teaching_plan_import_rejected"),
        (InvalidAcademicDate(), 400, "teaching_plan_import_rejected"),
        (FirestoreUnavailable(), 503, "teaching_plan_store_unavailable"),
        (UFMGSessionStoreUnavailable(), 503, "teaching_plan_store_unavailable"),
    ],
)
def test_teaching_plan_import_route_sanitizes_failures(
    monkeypatch: pytest.MonkeyPatch, error: Exception, status: int, code: str
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def import_plan(self, *_args: object, **_kwargs: object) -> None:
            raise error

    monkeypatch.setattr(function, "_moodle_teaching_plan_import_service", lambda *_: Service())
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/ufmg/import/teaching-plan",
                body_json={"course_id": "course-a", "term": "2026-2", "source_id": 701},
            )
        )
    )
    assert result["status"] == status
    assert result["body"] == {"error": code}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"course_id": "course-a", "term": "20262", "source_id": 701},
        {"course_id": 1, "term": "2026-2", "source_id": 701},
        {"course_id": "course-a", "term": "2026-2", "source_id": 0},
        {
            "course_id": "course-a",
            "term": "2026-2",
            "source_id": 701,
            "extra": True,
        },
    ],
)
def test_teaching_plan_import_rejects_invalid_bodies(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/import/teaching-plan", body_json=body))
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "teaching_plan_import_rejected"}


def test_teaching_plan_import_factory_shares_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"firestore": object(), "sessions": object(), "client": object()}
    monkeypatch.setattr(function, "_firestore", lambda *_: values["firestore"])
    monkeypatch.setattr(function, "_ufmg_session_store", lambda *_: values["sessions"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])
    monkeypatch.setattr(function, "_course_repository", lambda *_: "courses")

    service = function._moodle_teaching_plan_import_service({}, "user-1")

    assert service._sessions is values["sessions"]
    assert service._client is values["client"]
    assert service._courses == "courses"
    assert service._plans._firestore is values["firestore"]
    assert service._dates._firestore is values["firestore"]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"term": "20262", "course_id": 3701, "source_id": 701},
        {"term": "2026-2", "course_id": "3701", "source_id": 701},
        {"term": "2026-2", "course_id": 3701, "source_id": 0},
        {
            "term": "2026-2",
            "course_id": 3701,
            "source_id": 701,
            "unexpected": True,
        },
    ],
)
def test_moodle_material_files_route_rejects_invalid_bodies(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/material-files", body_json=body))
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_material_request_rejected"}


def test_moodle_material_service_factory_uses_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"tokens": object(), "client": object()}
    monkeypatch.setattr(function, "_moodle_token_store", lambda _headers: values["tokens"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])

    service = function._moodle_material_service({})

    assert service._tokens is values["tokens"]
    assert service._client is values["client"]


def test_moodle_token_store_builds_only_with_complete_secure_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = (
        "APPWRITE_FUNCTION_API_ENDPOINT",
        "APPWRITE_FUNCTION_PROJECT_ID",
        "SECURITY_DATABASE_ID",
        "UFMG_SESSION_TABLE_ID",
        "UFMG_SESSION_ACTIVE_KEY_VERSION",
        "UFMG_SESSION_ENCRYPTION_KEY_V1",
        "UFMG_SESSION_INDEX_KEY",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(UFMGSessionStoreUnavailable):
        function._moodle_token_store({})

    monkeypatch.setenv("APPWRITE_FUNCTION_API_ENDPOINT", "https://appwrite.example/v1")
    monkeypatch.setenv("APPWRITE_FUNCTION_PROJECT_ID", "project")
    monkeypatch.setenv("SECURITY_DATABASE_ID", "database")
    monkeypatch.setenv("UFMG_SESSION_TABLE_ID", "sessions")
    monkeypatch.setenv("UFMG_SESSION_ACTIVE_KEY_VERSION", "1")
    monkeypatch.setenv("UFMG_SESSION_ENCRYPTION_KEY_V1", b64encode(b"e" * 32).decode())
    monkeypatch.setenv("UFMG_SESSION_INDEX_KEY", b64encode(b"i" * 32).decode())

    store = function._moodle_token_store({"x-appwrite-key": "runtime-key"})

    assert store.__class__.__name__ == "AppwriteMoodleTokenStore"


def test_moodle_content_discovery_factory_uses_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "sessions": object(),
        "client": object(),
        "courses": object(),
        "catalog": object(),
    }
    captured: tuple[object, ...] = ()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _: values["sessions"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])
    monkeypatch.setattr(function, "_course_repository", lambda *_: values["courses"])
    monkeypatch.setattr(
        function, "_moodle_material_catalog_repository", lambda *_: values["catalog"]
    )

    class Service:
        def __init__(self, *dependencies: object) -> None:
            nonlocal captured
            captured = dependencies

    monkeypatch.setattr(function, "MoodleContentDiscoveryService", Service)
    assert function._moodle_content_discovery_service({}, "user").__class__ is Service
    assert captured == (
        values["sessions"],
        values["client"],
        values["courses"],
        values["catalog"],
    )


def test_moodle_material_catalog_factory_uses_server_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {"courses": object(), "catalog": object(), "firestore": object()}
    repository_factory = function._moodle_material_catalog_repository
    monkeypatch.setattr(function, "_course_repository", lambda *_: values["courses"])
    monkeypatch.setattr(
        function, "_moodle_material_catalog_repository", lambda *_: values["catalog"]
    )
    service = function._moodle_material_catalog_service({}, "user")
    assert service._courses is values["courses"]
    assert service._catalog is values["catalog"]

    monkeypatch.setattr(function, "_firestore", lambda *_: values["firestore"])
    repository = repository_factory({}, "user")
    assert repository._firestore is values["firestore"]


def test_academic_dates_route_returns_only_bounded_canonical_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Courses:
        def list_courses(self) -> list[dict[str, str]]:
            return [{"id": "dcc203", "code": "DCC203"}]

    class Dates:
        def __init__(self, _firestore: object) -> None:
            pass

        def list_dates(self, course_id: str) -> list[dict[str, object]]:
            assert course_id == "dcc203"
            return [
                {
                    "id": "moodle-910",
                    "title": "Trabalho prático",
                    "due_at": "2026-10-22T23:00:00Z",
                    "kind": "assignment",
                    "source": "moodle",
                    "source_id": "910",
                    "created_at": "2026-10-13T20:00:00Z",
                    "updated_at": "2026-10-13T20:00:00Z",
                }
            ]

    monkeypatch.setattr(function, "_course_repository", lambda *_: Courses())
    monkeypatch.setattr(function, "_firestore", lambda *_: object())
    monkeypatch.setattr(function, "AcademicDateRepository", Dates)
    context = FakeContext(FakeRequest("GET", "/v1/moodle/dates"))

    result = function.main(context)

    assert result["body"]["dates"][0]["course_code"] == "DCC203"
    assert result["body"]["dates"][0]["source_id"] == "910"
    assert json.loads(context.logs[0]) == {
        "event": "academic_date_list_succeeded",
        "count": 1,
        "course_count": 1,
    }


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (InvalidAcademicDate(), 500, "academic_dates_invalid"),
        (InvalidCourse(), 500, "academic_dates_invalid"),
        (FirestoreRequestRejected(), 500, "academic_dates_invalid"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
    ],
)
def test_academic_dates_route_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Courses:
        def list_courses(self) -> None:
            raise failure

    monkeypatch.setattr(function, "_course_repository", lambda *_: Courses())
    result = function.main(FakeContext(FakeRequest("GET", "/v1/moodle/dates")))
    assert result["status"] == status
    assert result["body"] == {"error": error}


def test_academic_dates_route_returns_auth_rejection_and_rejects_oversized_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("GET", "/v1/moodle/dates"))) is rejection

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Courses:
        def list_courses(self) -> list[dict[str, str]]:
            return [{"id": "dcc203", "code": "DCC203"}]

    class Dates:
        def __init__(self, _firestore: object) -> None:
            pass

        def list_dates(self, _course_id: str) -> list[dict[str, str]]:
            return [{"id": str(index), "due_at": "2026-10-22T23:00:00Z"} for index in range(501)]

    monkeypatch.setattr(function, "_course_repository", lambda *_: Courses())
    monkeypatch.setattr(function, "_firestore", lambda *_: object())
    monkeypatch.setattr(function, "AcademicDateRepository", Dates)
    result = function.main(FakeContext(FakeRequest("GET", "/v1/moodle/dates")))
    assert result["status"] == 500
    assert result["body"] == {"error": "academic_dates_invalid"}


def test_moodle_date_import_factory_composes_only_server_side_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "sessions": object(),
        "client": object(),
        "courses": object(),
        "firestore": object(),
        "dates": object(),
    }
    captured: tuple[object, ...] = ()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: values["sessions"])
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: values["client"])
    monkeypatch.setattr(function, "_course_repository", lambda *_: values["courses"])
    monkeypatch.setattr(function, "_firestore", lambda *_: values["firestore"])
    monkeypatch.setattr(function, "AcademicDateRepository", lambda value: values["dates"])

    class Service:
        def __init__(self, *dependencies: object) -> None:
            nonlocal captured
            captured = dependencies

    monkeypatch.setattr(function, "MoodleDateImportService", Service)
    assert function._moodle_date_import_service({}, "user").__class__ is Service
    assert captured == (
        values["sessions"],
        values["client"],
        values["courses"],
        values["dates"],
    )


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse(), 502, "moodle_response_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
        (InvalidAcademicDate(), 502, "moodle_date_import_rejected"),
        (InvalidCourse(), 502, "moodle_date_import_rejected"),
        (FirestoreRequestRejected(), 502, "moodle_date_import_rejected"),
        (TypeError(), 502, "moodle_date_import_rejected"),
        (ValueError(), 502, "moodle_date_import_rejected"),
    ],
)
def test_moodle_date_import_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Service:
        def import_dates(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_moodle_date_import_service", lambda *_: Service())
    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/dates")))
    assert result["status"] == status
    assert result["body"] == {"error": error}


def test_moodle_date_import_logs_only_a_bounded_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))

    class Service:
        def import_dates(self, *_args: Any, **_kwargs: Any) -> None:
            raise InvalidMoodleResponse("calendar_upstream_error")

    monkeypatch.setattr(function, "_moodle_date_import_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/import/dates"))

    result = function.main(context)

    assert result["status"] == 502
    assert json.loads(context.errors[0]) == {
        "event": "moodle_response_invalid",
        "reason": "calendar_upstream_error",
    }


def test_moodle_date_import_rejects_auth_and_nonempty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/dates"))) is rejection

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/import/dates", body_json={"bad": True}))
    )
    assert result["status"] == 400
    assert result["body"] == {"error": "moodle_date_import_rejected"}


def test_ufmg_sync_rejects_nonempty_payload_and_disabled_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(
        function,
        "_ufmg_sync_service",
        lambda *_args: pytest.fail("must reject before sync"),
    )

    invalid = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/sync", body_json={"force": True}))
    )
    disabled = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync")))

    assert invalid["status"] == 400
    assert invalid["body"] == {"error": "ufmg_sync_rejected"}
    assert disabled["status"] == 503
    assert disabled["body"] == {"error": "schedule_writes_disabled"}


def test_ufmg_sync_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync"))) is rejection


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (UFMGEnrollmentUnavailable(), 503, "ufmg_enrollment_unavailable"),
        (InvalidUFMGEnrollmentResponse(), 502, "ufmg_enrollment_invalid"),
        (MoodleUnavailable(), 503, "moodle_unavailable"),
        (InvalidMoodleResponse(), 502, "moodle_response_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
        (FirestoreRequestRejected(), 502, "ufmg_sync_rejected"),
        (InvalidCourse(), 502, "ufmg_sync_rejected"),
        (InvalidSchedule(), 502, "ufmg_sync_rejected"),
        (DuplicateCourseCode(), 502, "ufmg_sync_rejected"),
        (InvalidAcademicDate(), 502, "ufmg_sync_rejected"),
        (TypeError(), 502, "ufmg_sync_rejected"),
        (ValueError(), 502, "ufmg_sync_rejected"),
    ],
)
def test_ufmg_sync_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Service:
        def sync(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

        sync_siga = sync

    monkeypatch.setattr(function, "_ufmg_sync_service", lambda *_args: Service())

    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync")))

    assert result["status"] == status
    assert result["body"] == {"error": error}


def test_ufmg_sync_service_reuses_secure_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "sessions": object(),
        "enrollments": object(),
        "courses": object(),
        "schedules": object(),
        "dates": object(),
    }
    captured_importers: list[tuple[object, ...]] = []
    captured_sync: tuple[object, ...] = ()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: values["sessions"])
    monkeypatch.setattr(function, "UFMGEnrollmentClient", lambda: values["enrollments"])
    monkeypatch.setattr(function, "_course_repository", lambda _headers, _user: values["courses"])
    monkeypatch.setattr(
        function, "_schedule_repository", lambda _headers, _user: values["schedules"]
    )
    monkeypatch.setattr(
        function, "_moodle_date_import_service", lambda _headers, _user: values["dates"]
    )

    class Importer:
        def __init__(self, *dependencies: object) -> None:
            captured_importers.append(dependencies)

    class Sync:
        def __init__(self, *dependencies: object) -> None:
            nonlocal captured_sync
            captured_sync = dependencies

    monkeypatch.setattr(function, "UFMGCourseImportService", Importer)
    monkeypatch.setattr(function, "UFMGScheduleImportService", Importer)
    monkeypatch.setattr(function, "UFMGSyncService", Sync)

    assert function._ufmg_sync_service({}, "user").__class__ is Sync
    assert captured_importers == [
        (values["sessions"], values["enrollments"], values["courses"]),
        (
            values["sessions"],
            values["enrollments"],
            values["courses"],
            values["schedules"],
        ),
    ]
    assert captured_sync[:2] == (values["sessions"], values["enrollments"])
    assert captured_sync[-1] is values["dates"]


def test_ufmg_schedule_import_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/schedules"))) is rejection


def test_ufmg_schedule_import_service_uses_shared_secure_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "sessions": object(),
        "courses": object(),
        "schedules": object(),
    }
    captured: tuple[object, ...] = ()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: values["sessions"])
    monkeypatch.setattr(function, "_course_repository", lambda _headers, _user: values["courses"])
    monkeypatch.setattr(
        function, "_schedule_repository", lambda _headers, _user: values["schedules"]
    )
    monkeypatch.setattr(function, "UFMGEnrollmentClient", lambda: "enrollments")

    class Service:
        def __init__(self, *dependencies: object) -> None:
            nonlocal captured
            captured = dependencies

    monkeypatch.setattr(function, "UFMGScheduleImportService", Service)

    assert function._ufmg_schedule_import_service({}, "user").__class__ is Service
    assert captured == (
        values["sessions"],
        "enrollments",
        values["courses"],
        values["schedules"],
    )


def test_ufmg_schedule_import_rejects_body_and_disabled_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(
        function,
        "_ufmg_schedule_import_service",
        lambda *_args: pytest.fail("must reject before import"),
    )

    invalid = function.main(
        FakeContext(
            FakeRequest("POST", "/v1/ufmg/import/schedules", body_json={"unexpected": True})
        )
    )
    disabled = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/schedules")))

    assert invalid["status"] == 400
    assert invalid["body"] == {"error": "ufmg_schedule_import_rejected"}
    assert disabled["status"] == 503
    assert disabled["body"] == {"error": "schedule_writes_disabled"}


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (UFMGEnrollmentUnavailable(), 503, "ufmg_enrollment_unavailable"),
        (InvalidUFMGEnrollmentResponse(), 502, "ufmg_enrollment_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
        (FirestoreRequestRejected(), 502, "schedule_import_rejected"),
        (InvalidSchedule(), 502, "schedule_import_rejected"),
    ],
)
def test_ufmg_schedule_import_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Service:
        def import_schedules(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_ufmg_schedule_import_service", lambda *_args: Service())
    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/schedules")))

    assert result["status"] == status
    assert result["body"] == {"error": error}


def test_ufmg_course_import_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/import/courses"))) is rejection


def test_ufmg_course_import_rejects_an_unexpected_request_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setattr(
        function,
        "_ufmg_course_import_service",
        lambda *_args: pytest.fail("must reject before import"),
    )

    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/ufmg/import/courses",
                body_json={"unexpected": True},
            )
        )
    )

    assert result["status"] == 400
    assert result["body"] == {"error": "ufmg_course_import_rejected"}


def test_ufmg_course_import_service_uses_shared_secure_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = object()
    courses = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: store)
    monkeypatch.setattr(function, "_course_repository", lambda _headers, _user: courses)
    monkeypatch.setattr(function, "UFMGEnrollmentClient", lambda: "enrollments")

    class Service:
        def __init__(self, sessions: object, enrollments: object, repository: object) -> None:
            captured.update(sessions=sessions, enrollments=enrollments, repository=repository)

    monkeypatch.setattr(function, "UFMGCourseImportService", Service)

    assert function._ufmg_course_import_service({}, "user").__class__ is Service
    assert captured == {
        "sessions": store,
        "enrollments": "enrollments",
        "repository": courses,
    }


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (UFMGReauthenticationRequired(), 401, "ufmg_reauthentication_required"),
        (
            UFMGEnrollmentUnavailable("http_error", upstream_status=503),
            503,
            "ufmg_enrollment_unavailable",
        ),
        (InvalidUFMGEnrollmentResponse(), 502, "ufmg_enrollment_invalid"),
        (UFMGSessionStoreUnavailable(), 503, "ufmg_session_store_unavailable"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
        (FirestoreRequestRejected(), 502, "course_import_rejected"),
        (InvalidCourse(), 502, "course_import_rejected"),
    ],
)
def test_ufmg_course_import_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Service:
        def import_courses(self, *_args: Any, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_ufmg_course_import_service", lambda *_args: Service())
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/import/courses"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    expected_log: dict[str, Any] = {"event": error}
    if isinstance(failure, UFMGEnrollmentUnavailable):
        expected_log.update(reason="http_error", upstream_status=503)
    assert json.loads(context.errors[0]) == expected_log


def test_course_routes_list_save_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Repository:
        def list_courses(self) -> list[dict[str, str]]:
            return [{"id": "course-1"}]

        def save_course(self, payload: dict[str, Any]) -> dict[str, Any]:
            assert payload["id"] == "course-1"
            return payload

        def delete_course(self, course_id: str) -> None:
            assert course_id == "course-1"

    monkeypatch.setattr(function, "_course_repository", lambda *_args: Repository())

    listed = FakeContext(FakeRequest("GET", "/v1/courses"))
    saved = FakeContext(FakeRequest("PUT", "/v1/courses/course-1", body_json={"code": "DCC203"}))
    deleted = FakeContext(FakeRequest("DELETE", "/v1/courses/course-1"))

    assert function.main(listed)["body"] == {"courses": [{"id": "course-1"}]}
    assert function.main(saved)["body"]["course"]["id"] == "course-1"
    assert function.main(deleted)["body"] == {"deleted": True}
    assert json.loads(listed.logs[0]) == {"count": 1, "event": "course_list_succeeded"}
    assert json.loads(saved.logs[0]) == {"event": "course_save_succeeded"}
    assert json.loads(deleted.logs[0]) == {"event": "course_delete_succeeded"}


def test_schedule_routes_preview_and_save_with_bounded_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    result = {
        "course": {"id": "private-course"},
        "meetings": [],
        "changes": {
            "meeting_upserts": 1,
            "meeting_deletes": 0,
            "session_upserts": 3,
            "session_deletes": 0,
            "destructive_deletes": 0,
        },
    }

    class Repository:
        def get_schedule(self, course_id: str) -> dict[str, Any]:
            assert course_id == "course-1"
            return result

        def save_schedule(self, course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
            assert course_id == "course-1"
            assert payload == {"private": "payload"}
            return result

    monkeypatch.setattr(function, "_schedule_repository", lambda *_args: Repository())
    preview = FakeContext(FakeRequest("GET", "/v1/courses/course-1/schedule"))
    saved = FakeContext(
        FakeRequest("PUT", "/v1/courses/course-1/schedule", body_json={"private": "payload"})
    )

    assert function.main(preview)["body"] == result
    assert function.main(saved)["body"] == result
    assert json.loads(preview.logs[0]) == {
        "event": "schedule_preview_succeeded",
        **result["changes"],
    }
    assert json.loads(saved.logs[0]) == {"event": "schedule_save_succeeded", **result["changes"]}
    assert "private-course" not in "".join(preview.logs + saved.logs)


def test_schedule_write_switch_fails_closed_after_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[str] = []

    def authenticate(_context: Any, _origin: Any, route: str) -> tuple[str, None]:
        routes.append(route)
        return "user", None

    monkeypatch.setattr(function, "_authentication", authenticate)
    monkeypatch.delenv("ENABLE_SCHEDULE_WRITES", raising=False)
    context = FakeContext(FakeRequest("PUT", "/v1/courses/course-1/schedule"))

    result = function.main(context)

    assert result["status"] == 503
    assert result["body"] == {"error": "schedule_writes_disabled"}
    assert routes == ["/v1/courses/schedule/put"]
    assert json.loads(context.errors[0]) == {"event": "schedule_writes_disabled"}


def test_schedule_route_returns_authentication_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("GET", "/v1/courses/x/schedule"))) is rejection


@pytest.mark.parametrize(
    ("failure", "method", "status", "error", "extra"),
    [
        (ScheduleOverlap(), "PUT", 409, "schedule_overlap", {}),
        (InvalidSchedule(), "PUT", 400, "schedule_rejected", {}),
        (
            DestructiveScheduleChange(2),
            "PUT",
            409,
            "schedule_destructive_conflict",
            {"destructive_sessions": 2},
        ),
        (FirestoreNotFound(), "GET", 404, "course_not_found", {}),
        (FirestoreAccessDenied(), "GET", 403, "course_access_denied", {}),
        (FirestoreUnavailable(), "GET", 503, "course_store_unavailable", {}),
        (FirestoreRequestRejected(), "GET", 500, "schedule_data_invalid", {}),
    ],
)
def test_schedule_routes_sanitize_failures(
    failure: Exception,
    method: str,
    status: int,
    error: str,
    extra: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")

    class Repository:
        def get_schedule(self, _course_id: str) -> dict[str, Any]:
            raise failure

        def save_schedule(self, _course_id: str, _payload: dict[str, Any]) -> dict[str, Any]:
            raise failure

    monkeypatch.setattr(function, "_schedule_repository", lambda *_args: Repository())
    context = FakeContext(FakeRequest(method, "/v1/courses/course-1/schedule"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error, **extra}
    logged = json.loads(context.errors[0])
    assert logged["event"] == error
    assert "private" not in "".join(context.errors)


def test_course_routes_return_authentication_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))

    assert function.main(FakeContext(FakeRequest("GET", "/v1/courses"))) is rejection
    assert function.main(FakeContext(FakeRequest("DELETE", "/v1/courses/course-1"))) is rejection


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (InvalidCourse(), 500, "course_data_invalid"),
        (FirestoreRequestRejected(), 500, "course_data_invalid"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
    ],
)
def test_course_list_sanitizes_store_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Repository:
        def list_courses(self) -> list[dict[str, Any]]:
            raise failure

    monkeypatch.setattr(function, "_course_repository", lambda *_args: Repository())
    context = FakeContext(FakeRequest("GET", "/v1/courses"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    assert json.loads(context.errors[0]) == {"event": error}


@pytest.mark.parametrize(
    ("failure", "status", "error"),
    [
        (DuplicateCourseCode(), 409, "course_code_conflict"),
        (InvalidCourse(), 400, "course_rejected"),
        (FirestoreRequestRejected(), 400, "course_rejected"),
        (TypeError(), 400, "course_rejected"),
        (ValueError(), 400, "course_rejected"),
        (FirestoreNotFound(), 404, "course_not_found"),
        (FirestoreAccessDenied(), 403, "course_access_denied"),
        (FirestoreUnavailable(), 503, "course_store_unavailable"),
    ],
)
def test_course_mutation_sanitizes_failures(
    failure: Exception,
    status: int,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user", None))

    class Repository:
        def save_course(self, _payload: dict[str, Any]) -> dict[str, Any]:
            raise failure

    monkeypatch.setattr(function, "_course_repository", lambda *_args: Repository())
    context = FakeContext(FakeRequest("PUT", "/v1/courses/course-1"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    assert json.loads(context.errors[0]) == {"event": error}


def test_course_repository_uses_verified_uid_and_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(function, "FirestoreRestClient", Client)
    monkeypatch.setattr(function, "CourseRepository", lambda client: client)
    monkeypatch.setattr(function, "firebase_bearer_token", lambda _headers: "token")
    monkeypatch.setattr(function, "environ", {"FIREBASE_PROJECT_ID": "project"})

    repository = function._course_repository({"authorization": "private"}, "verified-user")

    assert repository is not None
    assert captured.pop("telemetry") is None
    assert captured == {
        "id_token": "token",
        "project_id": "project",
        "user_id": "verified-user",
    }


def test_schedule_repository_uses_the_shared_firestore_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object()
    monkeypatch.setattr(function, "_firestore", lambda *_args: client)
    monkeypatch.setattr(function, "ScheduleRepository", lambda value: ("schedule", value))

    assert function._schedule_repository({}, "user") == ("schedule", client)


def test_identity_route_accepts_verified_firebase_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "firebase-user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("registered", 2_000, "a" * 64),
    )
    consumed: list[dict[str, Any]] = []

    class Store:
        def consume(self, **kwargs: Any) -> None:
            consumed.append(kwargs)

    monkeypatch.setattr(function, "_security_store", lambda _headers: Store())
    monkeypatch.setattr(function, "time", lambda: 1_500)
    context = FakeContext(
        FakeRequest("GET", "/v1/identity", headers={"authorization": "Bearer private"})
    )

    result = function.main(context)

    assert result["body"] == {"authenticated": True}
    assert result["status"] == 200
    assert json.loads(context.logs[0]) == {"event": "request_authenticated"}
    assert consumed == [
        {
            "expires_at": 2_000,
            "now": 1_500,
            "route": "/v1/identity",
            "token_digest": "a" * 64,
            "user_id": "firebase-user",
            "enforce_replay": False,
        }
    ]
    assert "firebase-user" not in "".join(context.logs)
    assert "private" not in "".join(context.logs)


def test_identity_route_rejects_invalid_firebase_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_headers: dict[str, str]) -> str:
        raise InvalidIdentity("private-token")

    monkeypatch.setattr(function, "_firebase_identity", fail)
    context = FakeContext(
        FakeRequest("GET", "/v1/identity", headers={"authorization": "Bearer private-token"})
    )

    result = function.main(context)

    assert result["body"] == {"error": "unauthorized"}
    assert result["status"] == 401
    assert context.errors == ['{"event":"firebase_identity_rejected"}']
    assert json.loads(context.logs[-1])["status"] == 401
    assert "private-token" not in "".join(context.errors)


def test_preflight_allows_only_configured_exact_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frequencia-ufmg-eduardo.web.app")
    context = FakeContext(
        FakeRequest(
            "OPTIONS",
            "/v1/identity",
            headers={"origin": "https://frequencia-ufmg-eduardo.web.app"},
        )
    )

    result = function.main(context)

    assert result["status"] == 204
    assert result["headers"]["Access-Control-Allow-Origin"] == (
        "https://frequencia-ufmg-eduardo.web.app"
    )
    assert result["headers"]["Access-Control-Allow-Methods"] == ("GET,POST,PUT,DELETE,OPTIONS")
    assert "X-Firebase-AppCheck" in result["headers"]["Access-Control-Allow-Headers"]
    assert "X-Request-ID" in result["headers"]["Access-Control-Allow-Headers"]
    assert result["headers"]["Access-Control-Expose-Headers"] == "X-Request-ID"
    assert result["headers"]["Vary"] == "Origin"


def test_request_id_is_echoed_and_correlates_the_request_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frequencia-ufmg-eduardo.web.app")
    context = FakeContext(
        FakeRequest(
            "OPTIONS",
            "/v1/identity",
            headers={
                "origin": "https://frequencia-ufmg-eduardo.web.app",
                "X-Request-ID": "audit-course-list-123",
            },
        )
    )

    result = function.main(context)

    assert result["headers"]["X-Request-ID"] == "audit-course-list-123"
    assert json.loads(context.logs[-1]) == {
        "duration_ms": pytest.approx(0, abs=100),
        "event": "request_completed",
        "firestore_duration_ms": 0.0,
        "firestore_failures": 0,
        "firestore_reads": 0,
        "firestore_writes": 0,
        "method": "OPTIONS",
        "request_id": "audit-course-list-123",
        "route": "/v1/identity",
        "status": 204,
    }


def test_invalid_request_id_is_replaced_without_leaking_it() -> None:
    private_value = "private user@example.com"
    context = FakeContext(
        FakeRequest("OPTIONS", "/v1/identity", headers={"X-Request-ID": private_value})
    )

    result = function.main(context)

    request_id = result["headers"]["X-Request-ID"]
    assert request_id != private_value
    assert len(request_id) <= 64
    assert private_value not in "".join(context.logs)


def test_observability_failure_does_not_block_the_request() -> None:
    context = FakeContext(FakeRequest("OPTIONS", "/v1/identity"))

    def fail(_message: str) -> None:
        raise RuntimeError("logger unavailable")

    context.log = fail  # type: ignore[method-assign]

    result = function.main(context)

    assert result["status"] == 204
    assert json.loads(context.errors[-1]) == {
        "event": "observability_delivery_failed",
        "sink": "log",
    }


def test_error_observability_failure_does_not_block_the_rejection() -> None:
    context = FakeContext(
        FakeRequest("GET", "/v1/identity", headers={"origin": "https://evil.example"})
    )

    def fail(_message: str) -> None:
        raise RuntimeError("logger unavailable")

    context.error = fail  # type: ignore[method-assign]

    result = function.main(context)

    assert result["status"] == 403
    assert any(
        json.loads(message) == {"event": "observability_delivery_failed", "sink": "error"}
        for message in context.logs
    )


def test_total_observability_failure_does_not_block_the_request() -> None:
    context = FakeContext(FakeRequest("OPTIONS", "/v1/identity"))

    def fail(_message: str) -> None:
        raise RuntimeError("all telemetry unavailable")

    context.log = fail  # type: ignore[method-assign]
    context.error = fail  # type: ignore[method-assign]

    assert function.main(context)["status"] == 204


def test_unhandled_failure_is_correlated_and_re_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeContext(FakeRequest("GET", "/v1/identity"))
    monkeypatch.setattr(function, "_dispatch", lambda *_args: (_ for _ in ()).throw(RuntimeError()))

    with pytest.raises(RuntimeError):
        function.main(context)

    event = json.loads(context.errors[-1])
    assert event["event"] == "request_failed"
    assert event["request_id"].startswith("request-")
    assert event["route"] == "/v1/identity"


def test_firestore_telemetry_aggregates_without_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(function, "FirestoreRestClient", Client)
    monkeypatch.setattr(function, "firebase_bearer_token", lambda _headers: "token")
    monkeypatch.setattr(function, "environ", {"FIREBASE_PROJECT_ID": "project"})
    metrics = function._RequestMetrics()
    metrics_token = function._REQUEST_METRICS.set(metrics)
    try:
        function._firestore({}, "private-user")
        captured["telemetry"](
            "firestore_request_completed",
            {"duration_ms": 12.25, "kind": "read", "outcome": "succeeded"},
        )
        captured["telemetry"](
            "firestore_request_completed",
            {"duration_ms": 2, "kind": "write", "outcome": "failed"},
        )
        captured["telemetry"](
            "firestore_request_completed",
            {"duration_ms": "invalid", "kind": "read", "outcome": "succeeded"},
        )
    finally:
        function._REQUEST_METRICS.reset(metrics_token)

    assert metrics.snapshot() == {
        "firestore_duration_ms": 14.25,
        "firestore_failures": 1,
        "firestore_reads": 2,
        "firestore_writes": 1,
    }
    assert "private-user" not in json.dumps(metrics.snapshot())


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "https://frequencia-ufmg-eduardo.web.app.evil.example"],
)
def test_browser_request_rejects_unlisted_origin(
    origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frequencia-ufmg-eduardo.web.app")
    context = FakeContext(FakeRequest("GET", "/v1/identity", headers={"origin": origin}))

    result = function.main(context)

    assert result["status"] == 403
    assert result["body"] == {"error": "origin_forbidden"}
    assert "Access-Control-Allow-Origin" not in result["headers"]


def test_native_request_without_origin_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2, "a" * 64),
    )
    monkeypatch.setattr(
        function,
        "_security_store",
        lambda _headers: type("Store", (), {"consume": lambda self, **kwargs: None})(),
    )
    monkeypatch.setattr(function, "time", lambda: 1)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/identity")))

    assert result["status"] == 200
    assert "Access-Control-Allow-Origin" not in result["headers"]
    assert result["headers"]["Cache-Control"] == "no-store"
    assert result["headers"]["X-Content-Type-Options"] == "nosniff"


def test_request_rejects_oversized_or_false_content_length() -> None:
    oversized = FakeContext(FakeRequest("GET", "/v1/identity", body_binary=b"x" * 16_385))
    invalid = FakeContext(FakeRequest("GET", "/v1/identity", headers={"content-length": "invalid"}))

    assert function.main(oversized)["status"] == 413
    assert function.main(invalid)["status"] == 400


def test_request_rejects_declared_oversized_payload() -> None:
    context = FakeContext(FakeRequest("GET", "/v1/identity", headers={"content-length": "16385"}))

    assert function.main(context)["status"] == 413


def test_identity_route_rejects_invalid_app_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")

    def reject(_headers: dict[str, str], _now: int) -> FirebaseAppIdentity:
        raise InvalidAppCheck("private-token")

    monkeypatch.setattr(function, "_firebase_app", reject)

    context = FakeContext(FakeRequest("GET", "/v1/identity"))
    result = function.main(context)

    assert result["status"] == 401
    assert result["body"] == {"error": "app_check_invalid"}
    assert context.errors == ['{"event":"app_check_rejected","reason":"verification"}']
    assert "private-token" not in "".join(context.errors)


@pytest.mark.parametrize(
    ("failure", "status", "error", "event"),
    [
        (ReplayDetected("private"), 409, "app_check_replayed", "app_check_replayed"),
        (RateLimitExceeded(37), 429, "rate_limited", "rate_limit_exceeded"),
        (
            SecurityStoreUnavailable("private"),
            503,
            "security_guard_unavailable",
            "security_guard_unavailable",
        ),
    ],
)
def test_identity_route_fails_closed_on_guard_errors(
    failure: Exception,
    status: int,
    error: str,
    event: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_firebase_identity", lambda _headers: "user")
    monkeypatch.setattr(
        function,
        "_firebase_app",
        lambda _headers, _now: FirebaseAppIdentity("app", 2, "a" * 64),
    )
    monkeypatch.setattr(function, "time", lambda: 1)

    class Store:
        def consume(self, **_kwargs: Any) -> None:
            raise failure

    monkeypatch.setattr(function, "_security_store", lambda _headers: Store())
    context = FakeContext(FakeRequest("GET", "/v1/identity"))

    result = function.main(context)

    assert result["status"] == status
    assert result["body"] == {"error": error}
    assert json.loads(context.errors[0]) == {"event": event}
    assert "private" not in "".join(context.errors)
    if isinstance(failure, RateLimitExceeded):
        assert result["headers"]["Retry-After"] == "37"


def test_firebase_identity_uses_configured_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class Identity:
        uid = "firebase-user"

    def verify(headers: dict[str, str], project_id: str) -> Identity:
        calls.update(headers=headers, project_id=project_id)
        return Identity()

    monkeypatch.setattr(function, "verify_firebase_identity", verify)
    monkeypatch.setattr(function, "environ", {"FIREBASE_PROJECT_ID": "firebase-project"})

    uid = function._firebase_identity({"authorization": "Bearer private"})

    assert uid == "firebase-user"
    assert calls == {
        "headers": {"authorization": "Bearer private"},
        "project_id": "firebase-project",
    }


def test_firebase_app_uses_configured_project_and_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    expected = FirebaseAppIdentity("app", 2, "a" * 64)

    def verify(headers: dict[str, str], **kwargs: Any) -> FirebaseAppIdentity:
        calls.update(headers=headers, **kwargs)
        return expected

    monkeypatch.setattr(function, "verify_firebase_app_check", verify)
    monkeypatch.setattr(
        function,
        "environ",
        {
            "FIREBASE_PROJECT_NUMBER": "123",
            "FIREBASE_APP_IDS": " web-app, android-app, ",
        },
    )

    assert function._firebase_app({"x-firebase-appcheck": "private"}, 1) == expected
    assert calls == {
        "allowed_app_ids": {"web-app", "android-app"},
        "headers": {"x-firebase-appcheck": "private"},
        "now": 1,
        "project_number": "123",
    }


def test_security_store_uses_ephemeral_key_and_bounded_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}
    expected = object()

    class FakeClient:
        def set_endpoint(self, value: str) -> "FakeClient":
            calls["endpoint"] = value
            return self

        def set_project(self, value: str) -> "FakeClient":
            calls["project"] = value
            return self

        def set_key(self, value: str) -> "FakeClient":
            calls["key"] = value
            return self

    def make_store(tables: Any, **kwargs: Any) -> object:
        calls["tables"] = tables
        calls.update(kwargs)
        return expected

    monkeypatch.setattr(function, "Client", FakeClient)
    monkeypatch.setattr(function, "TablesDB", lambda client: ("tables", client))
    monkeypatch.setattr(function, "AppwriteSecurityStore", make_store)
    monkeypatch.setattr(
        function,
        "environ",
        {
            "APPWRITE_FUNCTION_API_ENDPOINT": "https://nyc.cloud.appwrite.io/v1",
            "APPWRITE_FUNCTION_PROJECT_ID": "project",
            "SECURITY_DATABASE_ID": "database",
            "SECURITY_TABLE_ID": "table",
            "RATE_LIMIT_PER_MINUTE": "12",
        },
    )

    assert function._security_store({"X-Appwrite-Key": "ephemeral"}) is expected
    assert calls["key"] == "ephemeral"
    assert calls["database_id"] == "database"
    assert calls["table_id"] == "table"
    assert calls["rate_limit"] == 12
    assert calls["window_seconds"] == 60


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {
            "APPWRITE_FUNCTION_API_ENDPOINT": "endpoint",
            "APPWRITE_FUNCTION_PROJECT_ID": "project",
            "SECURITY_DATABASE_ID": "database",
            "SECURITY_TABLE_ID": "table",
            "RATE_LIMIT_PER_MINUTE": "not-an-integer",
        },
    ],
)
def test_security_store_rejects_missing_or_invalid_config(
    environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(function, "environ", environment)

    with pytest.raises(SecurityStoreUnavailable):
        function._security_store({"x-appwrite-key": "ephemeral"})


def test_allowed_origin_supports_https_and_local_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        function,
        "environ",
        {
            "ALLOWED_ORIGINS": (
                "https://app.example,http://localhost:8080,http://127.0.0.1:3000,"
                "http://insecure.example"
            )
        },
    )

    assert function._allowed_origin("https://app.example") == "https://app.example"
    assert function._allowed_origin("http://localhost:8080") == "http://localhost:8080"
    assert function._allowed_origin("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    assert function._allowed_origin("http://insecure.example") is None
    assert function._allowed_origin("") is None


@pytest.mark.parametrize(
    ("headers", "body", "error"),
    [
        ({"content-length": "-1"}, b"", "invalid_content_length"),
        ({"content-length": "1"}, b"", None),
    ],
)
def test_payload_length_boundary(headers: dict[str, str], body: bytes, error: str | None) -> None:
    assert function._payload_error(headers, body) == error
