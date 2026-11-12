import json
from base64 import b64encode
from dataclasses import dataclass, field
from typing import Any

import pytest

import main as function
from academic_date_repository import InvalidAcademicDate
from appwrite_storage import StorageNotProvisioned, StorageUnavailable
from course_repository import DuplicateCourseCode
from course_service import InvalidCourse
from firebase_app_check import FirebaseAppIdentity, InvalidAppCheck
from firebase_identity import InvalidIdentity
from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRateLimited,
    FirestoreRequestRejected,
    FirestoreUnavailable,
)
from moodle_material_catalog_repository import InvalidMoodleMaterialCatalog
from moodle_structured_dates import InvalidMoodleResponse, MoodleUnavailable
from moodle_token_store import MoodleAuthorizationRequired, MoodleTokenStoreUnavailable
from official_calendar_service import InvalidOfficialCalendarRequest
from quota_guard import RateLimitExceeded, ReplayDetected, SecurityStoreUnavailable
from schedule_repository import DestructiveScheduleChange
from schedule_service import InvalidSchedule, ScheduleOverlap
from teaching_plan_repository import InvalidTeachingPlan
from ufmg_auth import InvalidUFMGCredentials, UFMGAuthenticationUnavailable
from ufmg_course_import import (
    InvalidUFMGEnrollmentResponse,
    UFMGEnrollmentUnavailable,
)
from ufmg_official_calendar import InvalidOfficialCalendar, OfficialCalendarUnavailable
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


def test_official_calendar_preview_and_apply_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def preview(self) -> dict[str, object]:
            return {"candidates": [], "counts": {"candidates": 0}}

        def apply(self, payload: object) -> dict[str, int]:
            assert payload == {"changes": [{"course_id": "c", "session_id": "s"}]}
            return {"applied": 1, "skipped": 0}

    monkeypatch.setattr(function, "_official_calendar_service", lambda *_: Service())
    preview = FakeContext(FakeRequest("POST", "/v1/calendar/official/preview"))
    applied = FakeContext(
        FakeRequest(
            "POST",
            "/v1/calendar/official/apply",
            body_json={"changes": [{"course_id": "c", "session_id": "s"}]},
        )
    )

    assert function.main(preview)["body"]["counts"] == {"candidates": 0}
    assert function.main(applied)["body"] == {"applied": 1, "skipped": 0}
    assert json.loads(preview.logs[0])["event"] == "official_calendar_preview_succeeded"


def test_official_calendar_route_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    context = FakeContext(FakeRequest("POST", "/v1/calendar/official/preview"))
    assert function.main(context) == rejection


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (InvalidOfficialCalendarRequest(), 400, "official_calendar_request_rejected"),
        (OfficialCalendarUnavailable(), 503, "official_calendar_unavailable"),
        (InvalidOfficialCalendar(), 502, "official_calendar_response_invalid"),
        (FirestoreAccessDenied("denied"), 403, "official_calendar_access_denied"),
        (FirestoreUnavailable("down"), 503, "official_calendar_store_unavailable"),
        (FirestoreNotFound("missing"), 409, "official_calendar_reconciliation_rejected"),
    ],
)
def test_official_calendar_route_maps_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def preview(self) -> dict[str, object]:
            raise failure

    monkeypatch.setattr(function, "_official_calendar_service", lambda *_: Service())
    context = FakeContext(FakeRequest("POST", "/v1/calendar/official/preview"))
    result = function.main(context)
    assert result["status"] == status
    assert result["body"] == {"error": code}
    assert json.loads(context.errors[0]) == {"action": "preview", "event": code}


def test_official_calendar_preview_rejects_a_nonempty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    context = FakeContext(
        FakeRequest("POST", "/v1/calendar/official/preview", body_json={"unexpected": True})
    )
    assert function.main(context)["status"] == 400


def test_official_calendar_factory_shares_authenticated_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    firestore = object()
    monkeypatch.setattr(function, "_firestore", lambda *_: firestore)
    service = function._official_calendar_service({}, "user-1")
    assert service._courses._firestore is firestore
    assert service._sessions._firestore is firestore


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
    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/moodle"))) is rejection

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


def test_unified_academic_sync_returns_summary_exceptions_and_diagnostic_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Service:
        def __init__(self, telemetry: Any) -> None:
            self.telemetry = telemetry

        def sync(self, user_id: str, *, now: int) -> dict[str, object]:
            assert user_id == "user-1"
            assert now > 0
            self.telemetry(
                "academic_sync_course_failed",
                {
                    "course_id": "course-b",
                    "course_code": "ESA019",
                    "stage": "teaching_plan_import",
                    "reason": "diario_plan_structure",
                },
            )
            return {
                "siga": {
                    "courses": {"created": 1},
                    "schedules": {"updated": 1},
                },
                "moodle": {
                    "dates": {"created": 2},
                    "content": {"candidate_total": 3},
                    "capabilities": None,
                },
                "teaching_plans": {
                    "available": 2,
                    "imported": 2,
                    "applied": 1,
                    "unchanged": 0,
                    "review_required": 1,
                },
                "exceptions": [
                    {
                        "course_id": "course-a",
                        "course_code": "ELE028",
                        "reason": "reconciliation_conflict",
                        "candidate_count": 1,
                        "changes": [],
                        "conflicting": 1,
                        "assessment_conflicts": 0,
                    }
                ],
            }

    monkeypatch.setattr(
        function,
        "_unified_academic_sync_service",
        lambda _headers, _user, telemetry: Service(telemetry),
    )
    context = FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all", body_json={}))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["teaching_plans"]["applied"] == 1
    assert result["body"]["exceptions"][0]["course_code"] == "ELE028"
    assert json.loads(context.logs[0]) == {
        "event": "academic_sync_succeeded",
        "exception_course_codes": ["ELE028"],
        "exception_reasons": ["reconciliation_conflict"],
        "plan_applied": 1,
        "plan_available": 2,
        "plan_imported": 2,
        "plan_unchanged": 0,
        "review_required": 1,
    }
    assert json.loads(context.errors[0]) == {
        "course_code": "ESA019",
        "course_id": "course-b",
        "event": "academic_sync_course_failed",
        "reason": "diario_plan_structure",
        "stage": "teaching_plan_import",
        "request_id": result["headers"]["X-Request-ID"],
    }


def test_unified_academic_sync_rejects_nonempty_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all", body_json={"apply": True}))
    )

    assert result["status"] == 400
    assert result["body"] == {"error": "academic_sync_rejected"}


@pytest.mark.parametrize("failure", [False, True])
def test_unified_sync_progress_reaches_terminal_state_and_preserves_failure_mapping(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    writes: list[dict[str, Any]] = []

    class Store:
        def patch_user_document(self, *args: str, fields: dict[str, Any]) -> dict[str, Any]:
            assert args == ("syncProgress", "current")
            writes.append(fields)
            return {"fields": fields}

    class Service:
        def __init__(self, telemetry: Any) -> None:
            self.telemetry = telemetry

        def sync(self, _user_id: str, *, now: int) -> dict[str, object]:
            self.telemetry("academic_sync_stage_completed", {"stage": "siga"})
            self.telemetry("academic_sync_stage_completed", {"stage": "moodle"})
            if failure:
                raise MoodleUnavailable("upstream unavailable")
            return {
                "exceptions": [],
                "teaching_plans": {
                    "available": 0,
                    "imported": 0,
                    "applied": 0,
                    "unchanged": 0,
                    "review_required": 0,
                },
            }

    monkeypatch.setattr(function, "_firestore", lambda *_: Store())
    monkeypatch.setattr(function, "_unified_academic_sync_service", lambda _, __, t: Service(t))
    context = FakeContext(
        FakeRequest("POST", "/v1/ufmg/sync/all", body_json={"progress_id": "sync-test123"})
    )
    result = function.main(context)
    assert result["status"] == (503 if failure else 200)
    assert writes[-1]["status"] == {"stringValue": "failed" if failure else "succeeded"}
    assert writes[-1]["completed"] == {"integerValue": "2" if failure else "3"}
    assert all(row["operationId"] == {"stringValue": "sync-test123"} for row in writes)


@pytest.mark.parametrize("identifier", [None, 3, "../secret", "x", "x" * 81])
def test_unified_sync_rejects_malformed_progress_identifier(
    monkeypatch: pytest.MonkeyPatch,
    identifier: object,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all", body_json={"progress_id": identifier}))
    )
    assert result["status"] == 400


@pytest.mark.parametrize(
    ("failure", "error", "status"),
    [
        (UFMGReauthenticationRequired(), "ufmg_reauthentication_required", 401),
        (
            UFMGEnrollmentUnavailable("http_error", upstream_status=503),
            "ufmg_enrollment_unavailable",
            503,
        ),
        (MoodleUnavailable(), "moodle_unavailable", 503),
        (InvalidMoodleResponse("course_list_json"), "moodle_response_invalid", 502),
        (UFMGSessionStoreUnavailable(), "academic_sync_store_unavailable", 503),
        (MoodleTokenStoreUnavailable(), "academic_sync_store_unavailable", 503),
        (FirestoreAccessDenied(), "academic_sync_access_denied", 403),
        (FirestoreUnavailable(), "academic_sync_store_unavailable", 503),
        (DuplicateCourseCode(), "academic_sync_rejected", 502),
        (InvalidAcademicDate(), "academic_sync_rejected", 502),
        (InvalidCourse(), "academic_sync_rejected", 502),
        (InvalidMoodleMaterialCatalog(), "academic_sync_rejected", 502),
        (InvalidSchedule(), "academic_sync_rejected", 502),
        (InvalidTeachingPlan(), "academic_sync_rejected", 502),
        (function.InvalidTeachingPlanReconciliation(), "academic_sync_rejected", 502),
        (FirestoreNotFound(), "academic_sync_rejected", 502),
        (FirestoreRequestRejected(), "academic_sync_rejected", 502),
        (TypeError(), "academic_sync_rejected", 502),
        (ValueError(), "academic_sync_rejected", 502),
    ],
)
def test_unified_academic_sync_maps_safe_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    error: str,
    status: int,
) -> None:
    class Service:
        def sync(self, _user_id: str, *, now: int) -> dict[str, object]:
            assert now > 0
            raise failure

    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    monkeypatch.setattr(function, "_unified_academic_sync_service", lambda *_: Service())

    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all")))

    assert result["status"] == status
    assert result["body"]["error"] == error


def test_unified_academic_sync_requires_authentication_and_write_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejection))
    assert function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all"))) is rejection

    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    monkeypatch.delenv("ENABLE_SCHEDULE_WRITES", raising=False)
    result = function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all")))
    assert result["body"] == {"error": "schedule_writes_disabled"}


def test_unified_academic_sync_factory_reuses_one_moodle_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = object()
    enrollments = object()
    client = type("Client", (), {"connection_count": 0})()
    firestore = object()
    tokens = object()
    monkeypatch.setattr(function, "_ufmg_session_store", lambda _headers: sessions)
    monkeypatch.setattr(function, "UFMGEnrollmentClient", lambda: enrollments)
    monkeypatch.setattr(function, "MoodleStructuredDatesClient", lambda: client)
    monkeypatch.setattr(function, "_firestore", lambda _headers, _user: firestore)
    monkeypatch.setattr(function, "_moodle_token_store", lambda _headers: tokens)
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: "pendencies")

    service = function._unified_academic_sync_service({}, "user")

    assert service._siga._dates._client is client
    assert service._moodle._dates._client is client
    assert service._moodle._content._client is client
    assert service._plans.importer._client is client


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
        "pendencies_created": 0,
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
            "pendencies_created",
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
            "pendencies_created": 0,
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
        "schedule_pendencies_created": 0,
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
            "pendencies_created": 0,
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
        "schedule_pendencies_created": 0,
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
        function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/capabilities"))) is rejection
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
        function.main(FakeContext(FakeRequest("POST", "/v1/ufmg/moodle/material-files")))
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
                "undated_assessment_total": 0,
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
    assert json.loads(context.logs[0]) == {
        "assessment_total": 2,
        "confidence": "authoritative",
        "course_id": "course-a",
        "criteria_total": 2,
        "dates_created": 2,
        "dates_removed": 0,
        "dates_unchanged": 0,
        "dates_updated": 0,
        "event": "teaching_plan_import_succeeded",
        "plan_outcome": "created",
        "schedule_total": 30,
        "source_id": "701",
        "term": "2026-2",
        "undated_assessment_total": 0,
    }


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


def test_teaching_plan_import_logs_actionable_parser_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    details = {
        "parser_stage": "required_sections",
        "row_count": 12,
        "nonempty_cell_count": 41,
        "max_row_cells": 7,
        "assessment_total": 2,
        "criteria_total": 1,
        "schedule_total": 0,
        "sample_rows": ["Atividade: MAT001 Cálculo I", "Cronograma"],
    }

    class Service:
        def import_plan(self, *_args: object, **_kwargs: object) -> None:
            raise InvalidMoodleResponse("diario_plan_structure", details=details)

    monkeypatch.setattr(function, "_moodle_teaching_plan_import_service", lambda *_: Service())
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/import/teaching-plan",
            body_json={"course_id": "course-a", "term": "2026-2", "source_id": 701},
            headers={"X-Request-ID": "teaching-plan-test"},
        )
    )

    result = function.main(context)

    assert result["status"] == 502
    diagnostic = json.loads(context.errors[0])
    assert diagnostic == {
        "assessment_total": 2,
        "course_id": "course-a",
        "criteria_total": 1,
        "event": "moodle_response_invalid",
        "max_row_cells": 7,
        "nonempty_cell_count": 41,
        "parser_stage": "required_sections",
        "reason": "diario_plan_structure",
        "request_id": "teaching-plan-test",
        "row_count": 12,
        "sample_rows": ["Atividade: MAT001 Cálculo I", "Cronograma"],
        "schedule_total": 0,
        "source_id": 701,
        "term": "2026-2",
    }
    serialized = context.errors[0].lower()
    assert "password" not in serialized
    assert "cookie" not in serialized
    assert "token" not in serialized


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


def test_teaching_plan_reconciliation_route_previews_and_logs_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Repository:
        def reconcile(self, course_id: str, *, apply: bool) -> dict[str, object]:
            assert (course_id, apply) == ("course-a", False)
            return {
                "course_id": course_id,
                "mode": "preview",
                "matched": 3,
                "missing": 1,
                "conflicting": 1,
                "assessments_linked": 2,
                "assessment_conflicts": 1,
                "outside_schedule": 1,
                "workload_validation": {
                    "status": "below_expected",
                    "expected_lesson_units": 60,
                    "actual_lesson_units": 58,
                    "difference_lesson_units": -2,
                },
                "applied": 0,
                "changes": [
                    {
                        "action": "create_session",
                        "occurrence_key": "2026-08-10T19:00-20:40",
                        "date": "2026-08-10",
                        "starts_at": "19:00",
                        "ends_at": "20:40",
                        "subject": "Polimorfismo",
                    }
                ],
                "excluded": [
                    {
                        "action": "excluded",
                        "occurrence_key": "2026-08-11T19:00-20:40",
                        "date": "2026-08-11",
                        "starts_at": "19:00",
                        "ends_at": "20:40",
                        "subject": "Atividade assíncrona",
                        "reason": "outside_weekly_schedule",
                    }
                ],
                "conflicts": [
                    {
                        "occurrence_key": "2026-08-10T19:00-20:40",
                        "reason": "overlapping_session",
                        "existing_session_ids": ["manual"],
                    }
                ],
            }

    monkeypatch.setattr(
        function, "_teaching_plan_reconciliation_repository", lambda *_: Repository()
    )
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/reconcile/teaching-plan",
            body_json={"course_id": "course-a", "apply": False},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["missing"] == 1
    assert json.loads(context.logs[0]) == {
        "applied": 0,
        "assessment_conflicts": 1,
        "assessments_linked": 2,
        "conflict_occurrence_keys": ["2026-08-10T19:00-20:40"],
        "conflicting": 1,
        "course_id": "course-a",
        "excluded_occurrences": [
            {
                "action": "excluded",
                "occurrence_key": "2026-08-11T19:00-20:40",
                "date": "2026-08-11",
                "starts_at": "19:00",
                "ends_at": "20:40",
                "subject": "Atividade assíncrona",
                "reason": "outside_weekly_schedule",
            }
        ],
        "event": "teaching_plan_reconciliation_succeeded",
        "matched": 3,
        "missing": 1,
        "mode": "preview",
        "outside_schedule": 1,
        "proposed_changes": [
            {
                "action": "create_session",
                "occurrence_key": "2026-08-10T19:00-20:40",
                "date": "2026-08-10",
                "starts_at": "19:00",
                "ends_at": "20:40",
                "subject": "Polimorfismo",
            }
        ],
        "workload_validation": {
            "status": "below_expected",
            "expected_lesson_units": 60,
            "actual_lesson_units": 58,
            "difference_lesson_units": -2,
        },
    }


@pytest.mark.parametrize("body", [{}, {"course_id": "course-a", "apply": 1}])
def test_teaching_plan_reconciliation_rejects_invalid_body(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))
    result = function.main(
        FakeContext(FakeRequest("POST", "/v1/ufmg/reconcile/teaching-plan", body_json=body))
    )
    assert result["status"] == 400


def test_teaching_plan_reconciliation_factory_uses_user_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    firestore = object()
    monkeypatch.setattr(function, "_firestore", lambda *_: firestore)

    repository = function._teaching_plan_reconciliation_repository({}, "user-1")

    assert repository._firestore is firestore


def test_teaching_plan_reconciliation_returns_authentication_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected = {"status": 401, "body": {"error": "identity_invalid"}}
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, rejected))
    result = function._teaching_plan_reconciliation(
        FakeContext(FakeRequest("POST", "/v1/ufmg/reconcile/teaching-plan")), None
    )
    assert result is rejected


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (FirestoreNotFound(), 404, "teaching_plan_not_found"),
        (InvalidTeachingPlan(), 400, "teaching_plan_reconciliation_rejected"),
        (FirestoreAccessDenied(), 403, "teaching_plan_reconciliation_access_denied"),
        (FirestoreUnavailable(), 503, "teaching_plan_reconciliation_store_unavailable"),
    ],
)
def test_teaching_plan_reconciliation_reports_actionable_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user-1", None))

    class Repository:
        def reconcile(self, *_args: object, **_kwargs: object) -> None:
            raise error

    monkeypatch.setattr(
        function, "_teaching_plan_reconciliation_repository", lambda *_: Repository()
    )
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/reconcile/teaching-plan",
            body_json={"course_id": "course-a", "apply": True},
        )
    )
    result = function.main(context)
    assert result["status"] == status
    assert result["body"] == {"error": code}
    assert json.loads(context.errors[0]) == {
        "course_id": "course-a",
        "event": code,
        "mode": "apply",
        "stage": {
            "teaching_plan_not_found": "load_teaching_plan",
            "teaching_plan_reconciliation_rejected": "validate_reconciliation",
            "teaching_plan_reconciliation_access_denied": "firestore_access",
            "teaching_plan_reconciliation_store_unavailable": "firestore_transport",
        }[code],
    }


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
        def __init__(self, *dependencies: object, telemetry: object = None) -> None:
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
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: values["pendencies"])
    values["pendencies"] = object()

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
            values["pendencies"],
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
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: values["pendencies"])
    values["pendencies"] = object()

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
        values["pendencies"],
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


@pytest.mark.parametrize("policy", [{}, {"modality": "online", "attendance_policy": "no_call"}])
def test_course_routes_list_save_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    policy: dict[str, str],
) -> None:
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
    saved = FakeContext(
        FakeRequest(
            "PUT",
            "/v1/courses/course-1",
            body_json={"code": "DCC203", **policy},
        )
    )
    deleted = FakeContext(FakeRequest("DELETE", "/v1/courses/course-1"))

    assert function.main(listed)["body"] == {"courses": [{"id": "course-1"}]}
    assert function.main(saved)["body"]["course"]["id"] == "course-1"
    assert function.main(deleted)["body"] == {"deleted": True}
    assert json.loads(listed.logs[0]) == {"count": 1, "event": "course_list_succeeded"}
    assert json.loads(saved.logs[0]) == {
        "event": "course_save_succeeded",
        "course_id": "course-1",
        "course_code": "DCC203",
        "modality": policy.get("modality", "in_person"),
        "attendance_policy": policy.get("attendance_policy", "required"),
        "session_history_preserved": True,
    }
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


@pytest.mark.parametrize(
    ("method", "route", "replay"),
    [
        ("GET", "/v1/identity", False),
        ("POST", "/v1/ufmg/moodle/material-files/post", False),
        ("POST", "/v1/ufmg/session/post", True),
        ("PUT", "/v1/courses/put", True),
    ],
)
def test_metadata_reads_keep_identity_app_check_and_budget_without_consuming_tokens(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    route: str,
    replay: bool,
) -> None:
    verified: list[str] = []

    def identity(_headers: Any) -> str:
        verified.append("identity")
        return "user"

    def app(_headers: Any, _now: int) -> FirebaseAppIdentity:
        verified.append("app_check")
        return FirebaseAppIdentity("registered", 2_000, "a" * 64)

    consumed: list[dict[str, Any]] = []

    class Store:
        def consume(self, **kwargs: Any) -> None:
            consumed.append(kwargs)

    monkeypatch.setattr(function, "_firebase_identity", identity)
    monkeypatch.setattr(function, "_firebase_app", app)
    monkeypatch.setattr(function, "_security_store", lambda _headers: Store())
    monkeypatch.setattr(function, "time", lambda: 1_500)
    user, error = function._authentication(FakeContext(FakeRequest(method, route)), None, route)
    assert user == "user" and error is None
    assert verified == ["identity", "app_check"]
    assert len(consumed) == 1
    assert consumed[0]["enforce_replay"] is replay
    assert consumed[0]["route"] == route
    assert consumed[0]["user_id"] == "user"


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
        "firestore_not_found": 0,
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
            {"duration_ms": 1, "kind": "read", "outcome": "not_found"},
        )
        captured["telemetry"](
            "firestore_request_completed",
            {"duration_ms": "invalid", "kind": "read", "outcome": "succeeded"},
        )
    finally:
        function._REQUEST_METRICS.reset(metrics_token)

    assert metrics.snapshot() == {
        "firestore_duration_ms": 15.25,
        "firestore_failures": 1,
        "firestore_not_found": 1,
        "firestore_reads": 3,
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
    assert "private" not in "".join(context.errors)
    if isinstance(failure, RateLimitExceeded):
        assert result["body"] == {"error": error, "error_code": "RATE_LIMITED"}
        assert result["headers"]["Retry-After"] == "37"
        logged = json.loads(context.errors[0])
        assert logged["event"] == event
        assert logged["status_code"] == 429
        assert logged["error_code"] == "RATE_LIMITED"
        assert logged["retry_after"] == 37
        diagnosis = function.production_telemetry.get_diagnosis(logged["request_id"])
        assert diagnosis is not None
        assert diagnosis["status_code"] == 429
        assert diagnosis["error_code"] == "RATE_LIMITED"
        assert diagnosis["retry_after"] == 37
    else:
        assert result["body"] == {"error": error}
        assert json.loads(context.errors[0]) == {"event": event}


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


class _FakePendencyRepo:
    def __init__(self, documents: dict[str, dict[str, Any]] | None = None) -> None:
        self.documents = documents or {}
        self.decisions: list[tuple[str, str, str]] = []
        self.fail_update = False
        self.list_error: Exception | None = None
        self.get_error: Exception | None = None
        self.update_error: Exception | None = None

    def _owned(self, pendency_id: str, user_id: str) -> dict[str, Any] | None:
        document = self.documents.get(pendency_id)
        if document is None or document.get("user_id") != user_id:
            return None
        return document

    def list_pendencies(
        self, user_id: str, course_id: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        if self.list_error is not None:
            raise self.list_error
        return [
            document
            for document in self.documents.values()
            if document.get("user_id") == user_id
            and (course_id is None or document.get("course_id") == course_id)
            and (status is None or document.get("status") == status)
        ]

    def get_pendency(self, pendency_id: str, user_id: str) -> dict[str, Any] | None:
        if self.get_error is not None:
            raise self.get_error
        return self._owned(pendency_id, user_id)

    def update_decision(
        self, pendency_id: str, user_id: str, decision: str, status: str = "resolved"
    ) -> bool:
        if self.fail_update:
            return False
        if self.update_error is not None:
            raise self.update_error
        document = self._owned(pendency_id, user_id)
        if document is None:
            return False
        self.decisions.append((pendency_id, decision, status))
        document["decision"] = decision
        document["status"] = status
        return True

    def delete_pendency(self, pendency_id: str, user_id: str) -> bool:
        if self._owned(pendency_id, user_id) is None:
            return False
        del self.documents[pendency_id]
        return True


class _FakeDraftRepo:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.fail_save = False
        self.list_error: Exception | None = None
        self.save_error: Exception | None = None
        self.delete_error: Exception | None = None

    def save_draft(self, **kwargs: Any) -> str:
        if self.fail_save:
            raise ValueError("rejected")
        if self.save_error is not None:
            raise self.save_error
        draft_id = f"draft-{len(self.documents) + 1}"
        self.documents[draft_id] = {"$id": draft_id, **kwargs}
        return draft_id

    def list_drafts(
        self, user_id: str, course_id: str | None = None, session_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.list_error is not None:
            raise self.list_error
        return [
            document
            for document in self.documents.values()
            if document.get("user_id") == user_id
            and (course_id is None or document.get("course_id") == course_id)
            and (session_id is None or document.get("session_id") == session_id)
        ]

    def delete_draft(self, draft_id: str, user_id: str) -> bool:
        if self.delete_error is not None:
            raise self.delete_error
        document = self.documents.get(draft_id)
        if document is None or document.get("user_id") != user_id:
            return False
        del self.documents[draft_id]
        return True


def _pend_document(pendency_id: str = "pend-1", **overrides: Any) -> dict[str, Any]:
    document = {
        "$id": pendency_id,
        "user_id": "user-1",
        "course_id": "course-1",
        "course_code": "DCC205",
        "course_name": "Estruturas",
        "current_schedule": "seg 08:00 (2 aulas)",
        "new_schedule": "ter 10:00 (2 aulas)",
        "reason": "manual_schedule_diverged",
        "decision": None,
        "status": "pending",
        "created_at": "2026-11-11T00:00:00Z",
        "updated_at": "2026-11-11T00:00:00Z",
        "payload": json.dumps(
            {
                "starts_on": "2026-08-03T00:00:00Z",
                "ends_on": "2026-12-05T00:00:00Z",
                "meetings": [
                    {
                        "id": "ufmg-2-600-2",
                        "weekday": 2,
                        "start_minutes": 600,
                        "lesson_count": 2,
                        "call_count": 1,
                    }
                ],
                "confirm_destructive": False,
            }
        ),
    }
    document.update(overrides)
    return document


def _auth_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user-1", None))


def test_schedule_pendencies_list_returns_public_view(monkeypatch: pytest.MonkeyPatch) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    context = FakeContext(FakeRequest("GET", "/v1/schedule/pendencies"))
    result = function.main(context)

    assert result["status"] == 200
    (item,) = result["body"]["pendencies"]
    assert item["id"] == "pend-1"
    assert item["course_code"] == "DCC205"
    assert item["current_schedule"] == "seg 08:00 (2 aulas)"
    assert item["new_schedule"] == "ter 10:00 (2 aulas)"
    assert item["reason"] == "manual_schedule_diverged"
    assert item["status"] == "pending"
    assert "payload" not in item
    assert json.loads(context.logs[0])["event"] == "schedule_pendencies_listed"


def test_schedule_pendencies_list_fails_closed_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)

    def no_store(_headers: dict[str, str]) -> Any:
        raise SecurityStoreUnavailable("down")

    monkeypatch.setattr(function, "_pendency_repository", no_store)
    result = function.main(FakeContext(FakeRequest("GET", "/v1/schedule/pendencies")))
    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"


def test_schedule_pendency_decision_requires_valid_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: _FakePendencyRepo())
    path = "/v1/schedule/pendencies/pend-1/decision"

    assert function.main(FakeContext(FakeRequest("POST", path, body_json="nope")))["status"] == 400
    assert function.main(FakeContext(FakeRequest("POST", path, body_json={})))["status"] == 400
    invalid = function.main(
        FakeContext(FakeRequest("POST", path, body_json={"decision": "invalid"}))
    )
    assert invalid["status"] == 400
    assert invalid["body"]["error"] == "pendency_decision_invalid"
    pending = function.main(
        FakeContext(FakeRequest("POST", path, body_json={"decision": "pendente"}))
    )
    assert pending["status"] == 400


def test_schedule_pendency_decision_404_and_update_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo()
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)
    missing = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/missing/decision",
                body_json={"decision": "manter_atual"},
            )
        )
    )
    assert missing["status"] == 404
    assert missing["body"]["error"] == "pendency_not_found"

    repo2 = _FakePendencyRepo({"pend-1": _pend_document()})
    repo2.fail_update = True
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo2)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "manter_atual"},
            )
        )
    )
    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"


def test_schedule_pendency_decision_manter_atual_persists_without_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    def apply_should_not_run(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("manter_atual must not touch the schedule")

    monkeypatch.setattr(function, "_apply_pendency_payload", apply_should_not_run)
    context = FakeContext(
        FakeRequest(
            "POST",
            "/v1/schedule/pendencies/pend-1/decision",
            body_json={"decision": "manter_atual"},
        )
    )
    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["applied"] is False
    assert result["body"]["pendency"]["decision"] == "manter_atual"
    assert result["body"]["pendency"]["status"] == "resolved"
    assert repo.decisions == [("pend-1", "manter_atual", "resolved")]
    assert repo.documents["pend-1"]["decision"] == "manter_atual"
    event = json.loads(context.logs[0])
    assert event["event"] == "schedule_pendency_decided"
    assert event["decision"] == "manter_atual"
    assert event["applied"] is False


def test_schedule_pendency_decision_aplicar_mudanca_applies_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)
    applied_calls: list[str] = []

    def fake_apply(context: Any, user_id: str, document: dict[str, Any]) -> bool:
        applied_calls.append(user_id)
        return True

    monkeypatch.setattr(function, "_apply_pendency_payload", fake_apply)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "aplicar_mudanca"},
            )
        )
    )

    assert result["status"] == 200
    assert result["body"]["applied"] is True
    assert result["body"]["pendency"]["decision"] == "aplicar_mudanca"
    assert repo.decisions == [("pend-1", "aplicar_mudanca", "resolved")]
    assert applied_calls == ["user-1"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (DestructiveScheduleChange(2), 409, "pendency_apply_conflict"),
        (ScheduleOverlap("overlap"), 409, "pendency_apply_conflict"),
        (FirestoreNotFound("missing"), 404, "course_not_found"),
        (FirestoreAccessDenied("denied"), 403, "course_access_denied"),
        (FirestoreUnavailable("down"), 503, "pendency_apply_failed"),
        (FirestoreRequestRejected("bad"), 503, "pendency_apply_failed"),
        (InvalidSchedule("bad"), 503, "pendency_apply_failed"),
        (InvalidCourse("bad"), 503, "pendency_apply_failed"),
        (TypeError("bad"), 503, "pendency_apply_failed"),
        (ValueError("bad"), 503, "pendency_apply_failed"),
    ],
)
def test_schedule_pendency_decision_apply_failures_do_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    code: str,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    def failing_apply(*_args: Any, **_kwargs: Any) -> bool:
        raise error

    monkeypatch.setattr(function, "_apply_pendency_payload", failing_apply)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "aplicar_mudanca"},
            )
        )
    )
    assert result["status"] == status
    assert result["body"]["error"] == code
    assert repo.decisions == []


def test_apply_pendency_payload_applies_stored_change_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = {"id": "course-1", "code": "DCC205"}
    other = {"id": "course-2", "code": "MAT001"}
    saved: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    loaded: list[list[dict[str, Any]]] = []

    class CourseRepo:
        def get_course(self, course_id: str) -> dict[str, Any]:
            assert course_id == "course-1"
            return course

        def list_courses(self) -> list[dict[str, Any]]:
            return [course, other]

    class ScheduleRepo:
        def load_import_schedules(self, courses: list[dict[str, Any]]) -> dict[str, Any]:
            loaded.append(courses)
            return {
                "course-1": {"course": course, "meetings": []},
                "course-2": {"course": other, "meetings": []},
            }

        def save_import_schedule(
            self,
            course_id: str,
            payload: dict[str, Any],
            schedules: dict[str, Any],
        ) -> dict[str, Any]:
            saved.append((course_id, dict(payload), dict(schedules)))
            return {"changes": {}}

    monkeypatch.setattr(function, "_course_repository", lambda _h, _u: CourseRepo())
    monkeypatch.setattr(function, "_schedule_repository", lambda _h, _u: ScheduleRepo())

    context = FakeContext(FakeRequest("POST", "/v1/schedule/pendencies/pend-1/decision"))
    assert function._apply_pendency_payload(context, "user-1", _pend_document()) is True
    course_id, payload, schedules = saved[0]
    assert course_id == "course-1"
    # the safe flow never forces destructive confirmation
    assert payload["confirm_destructive"] is False
    assert payload["meetings"][0]["id"] == "ufmg-2-600-2"
    # every other course schedule participates in the overlap check
    assert {item["id"] for item in loaded[0]} == {"course-1", "course-2"}
    assert set(schedules) == {"course-1", "course-2"}


def test_apply_pendency_payload_falls_back_to_course_when_listing_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = {"id": "course-1", "code": "DCC205"}
    loaded: list[list[dict[str, Any]]] = []

    class CourseRepo:
        def get_course(self, course_id: str) -> dict[str, Any]:
            return course

        def list_courses(self) -> list[dict[str, Any]]:
            return []

    class ScheduleRepo:
        def load_import_schedules(self, courses: list[dict[str, Any]]) -> dict[str, Any]:
            loaded.append(courses)
            return {"course-1": {"course": course, "meetings": []}}

        def save_import_schedule(
            self, course_id: str, payload: dict[str, Any], schedules: dict[str, Any]
        ) -> dict[str, Any]:
            return {"changes": {}}

    monkeypatch.setattr(function, "_course_repository", lambda _h, _u: CourseRepo())
    monkeypatch.setattr(function, "_schedule_repository", lambda _h, _u: ScheduleRepo())

    context = FakeContext(FakeRequest("POST", "/v1/schedule/pendencies/pend-1/decision"))
    assert function._apply_pendency_payload(context, "user-1", _pend_document()) is True
    assert loaded[0] == [course]


def test_apply_pendency_payload_without_payload_returns_false() -> None:
    context = FakeContext(FakeRequest("POST", "/v1/schedule/pendencies/pend-1/decision"))
    assert (
        function._apply_pendency_payload(context, "user-1", _pend_document(payload=None)) is False
    )
    with pytest.raises(ValueError):
        function._apply_pendency_payload(context, "user-1", _pend_document(payload="[1]"))


def test_registration_draft_routes_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)

    save = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/registration/drafts",
                body_json={
                    "course_id": "course-1",
                    "course_code": "DCC205",
                    "session_id": "new",
                    "form_data": {"code": "DCC205", "name": "Estruturas"},
                    "last_error": "rate_limited",
                    "attempt_count": 2,
                },
            )
        )
    )
    assert save["status"] == 200
    draft_id = save["body"]["draft"]["id"]

    listed = function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))
    assert listed["status"] == 200
    (item,) = listed["body"]["drafts"]
    assert item["id"] == draft_id
    assert item["form_data"] == {"code": "DCC205", "name": "Estruturas"}
    assert item["last_error"] == "rate_limited"
    assert item["attempt_count"] == 2

    deleted = function.main(
        FakeContext(FakeRequest("DELETE", f"/v1/registration/drafts/{draft_id}"))
    )
    assert deleted["status"] == 200
    assert deleted["body"] == {"deleted": True, "id": draft_id}
    missing = function.main(FakeContext(FakeRequest("DELETE", "/v1/registration/drafts/nope")))
    assert missing["status"] == 404


def test_registration_draft_save_validates_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)
    path = "/v1/registration/drafts"

    assert function.main(FakeContext(FakeRequest("POST", path, body_json="nope")))["status"] == 400
    assert function.main(FakeContext(FakeRequest("POST", path, body_json={})))["status"] == 400
    bad_id = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                path,
                body_json={
                    "course_id": "bad/id",
                    "course_code": "X",
                    "session_id": "s",
                    "form_data": {},
                },
            )
        )
    )
    assert bad_id["status"] == 400
    coerced = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                path,
                body_json={
                    "course_id": "course-1",
                    "course_code": "X",
                    "session_id": "s",
                    "form_data": {"a": 1},
                    "last_error": 5,
                    "attempt_count": True,
                },
            )
        )
    )
    assert coerced["status"] == 200

    repo.fail_save = True
    rejected = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                path,
                body_json={
                    "course_id": "course-1",
                    "course_code": "X",
                    "session_id": "s",
                    "form_data": {},
                },
            )
        )
    )
    assert rejected["status"] == 400
    assert rejected["body"]["error"] == "draft_rejected"


def test_registration_draft_routes_fail_closed_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)

    def no_store(_headers: dict[str, str]) -> Any:
        raise SecurityStoreUnavailable("down")

    monkeypatch.setattr(function, "_draft_repository", no_store)
    assert (
        function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))["status"] == 503
    )
    posted = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/registration/drafts",
                body_json={
                    "course_id": "c",
                    "course_code": "X",
                    "session_id": "s",
                    "form_data": {},
                },
            )
        )
    )
    assert posted["status"] == 503
    assert (
        function.main(FakeContext(FakeRequest("DELETE", "/v1/registration/drafts/d1")))["status"]
        == 503
    )


def test_firestore_rate_limited_becomes_429_with_preserved_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user-1", None))

    class Service:
        def list_courses(self) -> list[dict[str, Any]]:
            raise FirestoreRateLimited(
                "Firestore rate limit exceeded",
                status_code=429,
                error_code="RESOURCE_EXHAUSTED",
                retry_after=42,
            )

    monkeypatch.setattr(function, "_course_repository", lambda _h, _u: Service())
    context = FakeContext(FakeRequest("GET", "/v1/courses"))

    result = function.main(context)

    assert result["status"] == 429
    assert result["body"] == {"error": "rate_limited", "error_code": "RESOURCE_EXHAUSTED"}
    assert result["headers"]["Retry-After"] == "42"
    events = [json.loads(row) for row in context.errors]
    error_event = next(item for item in events if item["event"] == "resource_exhausted")
    assert error_event["status_code"] == 429
    assert error_event["error_code"] == "RESOURCE_EXHAUSTED"
    assert error_event["retry_after"] == 42
    diagnosis = function.production_telemetry.get_diagnosis(error_event["request_id"])
    assert diagnosis is not None
    assert diagnosis["status_code"] == 429
    assert diagnosis["error_code"] == "RESOURCE_EXHAUSTED"


def test_firestore_rate_limited_without_retry_after_omits_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "_authentication", lambda *_args: ("user-1", None))

    class Service:
        def list_courses(self) -> list[dict[str, Any]]:
            raise FirestoreRateLimited("Firestore rate limit exceeded")

    monkeypatch.setattr(function, "_course_repository", lambda _h, _u: Service())
    result = function.main(FakeContext(FakeRequest("GET", "/v1/courses")))

    assert result["status"] == 429
    assert "Retry-After" not in result["headers"]


def test_repeated_identical_report_within_one_request_writes_one_log() -> None:
    context = FakeContext(FakeRequest("GET", "/v1/identity"))
    token = function._REQUEST_ID.set("req-repeat-1")
    try:
        function._log(context, "repeated_report", course_id="course-1", outcome="ok")
        function._log(context, "repeated_report", course_id="course-1", outcome="ok", duration_ms=5)
        function._log(context, "repeated_report", course_id="course-1", outcome="failed")
        function._log(context, "other_report", course_id="course-1")
    finally:
        function._REQUEST_ID.reset(token)

    events = [json.loads(row)["event"] for row in context.logs]
    assert events == ["repeated_report", "repeated_report", "other_report"]
    assert json.loads(context.logs[1])["outcome"] == "failed"


def test_route_names_cover_pendency_and_draft_paths() -> None:
    assert function._route_name("/v1/schedule/pendencies") == "/v1/schedule/pendencies"
    assert (
        function._route_name(
            "/v1/schedule/dependencies/abc/decision".replace("dependencies", "pendencies")
        )
        == "/v1/schedule/pendencies/:pendency_id/decision"
    )
    assert function._route_name("/v1/registration/drafts") == "/v1/registration/drafts"
    assert (
        function._route_name("/v1/registration/drafts/xyz") == "/v1/registration/drafts/:draft_id"
    )
    assert function._is_public_api_path("/v1/schedule/pendencies")
    assert function._is_public_api_path("/v1/registration/drafts")


def test_appwrite_client_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(function, "environ", {})
    with pytest.raises(SecurityStoreUnavailable):
        function._appwrite_client({})


def test_new_route_auth_rejections(monkeypatch: pytest.MonkeyPatch) -> None:
    rejection = {"status": 401}
    monkeypatch.setattr(function, "_authentication", lambda *_args: (None, rejection))
    assert function.main(FakeContext(FakeRequest("GET", "/v1/schedule/pendencies"))) is rejection
    assert (
        function.main(
            FakeContext(
                FakeRequest(
                    "POST",
                    "/v1/schedule/pendencies/p/decision",
                    body_json={"decision": "manter_atual"},
                )
            )
        )
        is rejection
    )
    assert (
        function.main(FakeContext(FakeRequest("POST", "/v1/registration/drafts", body_json={})))
        is rejection
    )
    assert function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts"))) is rejection
    assert (
        function.main(FakeContext(FakeRequest("DELETE", "/v1/registration/drafts/d"))) is rejection
    )


def test_appwrite_client_builds_with_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        function,
        "environ",
        {
            "APPWRITE_FUNCTION_API_ENDPOINT": "https://cloud.appwrite.io/v1",
            "APPWRITE_FUNCTION_PROJECT_ID": "project",
        },
    )
    client = function._appwrite_client({"X-Appwrite-Key": "key"})
    assert client is not None
    assert (
        function._pendency_repository({"X-Appwrite-Key": "key"}).__class__.__name__
        == "PendencyRepository"
    )
    assert (
        function._draft_repository({"X-Appwrite-Key": "key"}).__class__.__name__
        == "DraftRepository"
    )


def test_registration_drafts_list_skips_non_dict_form_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    repo.documents["draft-raw"] = {
        "$id": "draft-raw",
        "user_id": "user-1",
        "form_data": "not-a-dict",
    }
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))

    assert result["status"] == 200
    assert result["body"]["drafts"][0]["form_data"] == "not-a-dict"


def test_schedule_pendency_decision_fails_closed_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)

    def no_store(_headers: dict[str, str]) -> Any:
        raise SecurityStoreUnavailable("down")

    monkeypatch.setattr(function, "_pendency_repository", no_store)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "manter_atual"},
            )
        )
    )
    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"


def test_schedule_pendencies_list_is_scoped_to_the_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo(
        {
            "pend-1": _pend_document("pend-1", user_id="user-1"),
            "pend-2": _pend_document("pend-2", user_id="user-2"),
        }
    )
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/schedule/pendencies")))

    assert result["status"] == 200
    assert [item["id"] for item in result["body"]["pendencies"]] == ["pend-1"]


def test_schedule_pendencies_list_fails_closed_on_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    repo.list_error = StorageUnavailable("down")
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/schedule/pendencies")))

    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"
    repo.list_error = StorageNotProvisioned("collection_not_found")
    result = function.main(FakeContext(FakeRequest("GET", "/v1/schedule/pendencies")))
    assert result["status"] == 503


def test_schedule_pendency_decision_cannot_touch_another_users_pendency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document("pend-1", user_id="user-2")})
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    def apply_must_not_run(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("another user's pendency must not be applied")

    monkeypatch.setattr(function, "_apply_pendency_payload", apply_must_not_run)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "aplicar_mudanca"},
            )
        )
    )
    assert result["status"] == 404
    assert result["body"]["error"] == "pendency_not_found"
    assert repo.decisions == []


def test_schedule_pendency_decision_get_failure_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    repo.get_error = StorageUnavailable("down")
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "manter_atual"},
            )
        )
    )
    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"


def test_registration_drafts_are_isolated_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)

    for user in ("user-1", "user-2"):
        monkeypatch.setattr(function, "_authentication", lambda *_a, u=user: (u, None))
        saved = function.main(
            FakeContext(
                FakeRequest(
                    "POST",
                    "/v1/registration/drafts",
                    body_json={
                        "course_id": "course-1",
                        "course_code": "DCC205",
                        "session_id": "course-create",
                        "form_data": {"code": "DCC205"},
                    },
                )
            )
        )
        assert saved["status"] == 200

    monkeypatch.setattr(function, "_authentication", lambda *_a: ("user-1", None))
    listed = function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))
    assert listed["status"] == 200
    assert len(listed["body"]["drafts"]) == 1
    own_id = listed["body"]["drafts"][0]["id"]

    # user-1 cannot delete user-2's draft
    monkeypatch.setattr(function, "_authentication", lambda *_a: ("user-2", None))
    listed2 = function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))
    other_id = listed2["body"]["drafts"][0]["id"]
    monkeypatch.setattr(function, "_authentication", lambda *_a: ("user-1", None))
    denied = function.main(
        FakeContext(FakeRequest("DELETE", f"/v1/registration/drafts/{other_id}"))
    )
    assert denied["status"] == 404
    assert other_id in repo.documents
    deleted = function.main(FakeContext(FakeRequest("DELETE", f"/v1/registration/drafts/{own_id}")))
    assert deleted["status"] == 200


def test_registration_drafts_list_fails_closed_on_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    repo.list_error = StorageNotProvisioned("collection_not_found")
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)

    result = function.main(FakeContext(FakeRequest("GET", "/v1/registration/drafts")))

    assert result["status"] == 503
    assert result["body"]["error"] == "draft_store_unavailable"


def test_storage_ensure_route_provisions_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_client(_headers: dict[str, str]) -> object:
        return object()

    def fake_ensure(databases: object) -> dict[str, Any]:
        calls.append("ensure")
        return {"database": "created", "collections": {}}

    def fake_validate(databases: object) -> dict[str, Any]:
        calls.append("validate")
        return {"database": "frequencia_ufmg", "collections": []}

    monkeypatch.setattr(function, "_appwrite_client", fake_client)
    monkeypatch.setattr(function, "Databases", lambda client: object())
    monkeypatch.setattr(function, "ensure_appwrite_storage", fake_ensure)
    monkeypatch.setattr(function, "validate_appwrite_storage", fake_validate)

    context = FakeContext(FakeRequest("POST", "/internal/storage/ensure"))
    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["storage"]["database"] == "created"
    assert calls == ["ensure", "validate"]
    assert json.loads(context.logs[0])["event"] == "storage_ensure_succeeded"


def test_storage_ensure_route_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_client(_headers: dict[str, str]) -> object:
        raise SecurityStoreUnavailable("down")

    monkeypatch.setattr(function, "_appwrite_client", no_client)
    result = function.main(FakeContext(FakeRequest("POST", "/internal/storage/ensure")))
    assert result["status"] == 503
    assert result["body"]["error"] == "storage_store_unavailable"

    monkeypatch.setattr(function, "_appwrite_client", lambda _h: object())
    monkeypatch.setattr(function, "Databases", lambda client: object())

    def failing_ensure(databases: object) -> dict[str, Any]:
        raise StorageUnavailable("down")

    monkeypatch.setattr(function, "ensure_appwrite_storage", failing_ensure)
    context = FakeContext(FakeRequest("POST", "/internal/storage/ensure"))
    result = function.main(context)
    assert result["status"] == 503
    assert result["body"]["error"] == "storage_ensure_failed"
    assert json.loads(context.errors[0])["event"] == "storage_ensure_failed"


def _real_schedule_factories(monkeypatch: pytest.MonkeyPatch, store: Any) -> None:
    from test_schedule_repository import NOW

    from course_repository import CourseRepository
    from schedule_repository import ScheduleRepository

    monkeypatch.setattr(
        function, "_course_repository", lambda _h, _u: CourseRepository(store, now=lambda: NOW)
    )
    monkeypatch.setattr(
        function, "_schedule_repository", lambda _h, _u: ScheduleRepository(store, now=lambda: NOW)
    )


def test_pendency_apply_rejects_overlap_with_another_course_and_keeps_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_schedule_repository import FakeFirestore

    _auth_ok(monkeypatch)
    store = FakeFirestore(overlap=True)
    _real_schedule_factories(monkeypatch, store)
    payload = {
        "starts_on": "2026-08-04T00:00:00Z",
        "ends_on": "2026-08-18T00:00:00Z",
        "meetings": [
            {
                "id": "ufmg-2-1140-2",
                "weekday": 2,
                "start_minutes": 1140,
                "lesson_count": 2,
                "call_count": 1,
            }
        ],
        "confirm_destructive": True,  # stored payload is overridden by the safe flow
    }
    repo = _FakePendencyRepo(
        {"pend-1": _pend_document("pend-1", course_id="poo", payload=json.dumps(payload))}
    )
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "aplicar_mudanca"},
            )
        )
    )

    assert result["status"] == 409
    assert result["body"]["error"] == "pendency_apply_conflict"
    assert repo.decisions == []  # not resolved
    assert store.commits == []  # nothing written


def test_pendency_apply_preserves_sessions_with_attendance_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_schedule_repository import FakeFirestore

    _auth_ok(monkeypatch)
    store = FakeFirestore(protected=True)  # 2026-08-04 session has attendance_status=presente
    _real_schedule_factories(monkeypatch, store)
    payload = {
        "starts_on": "2026-08-04T00:00:00Z",
        "ends_on": "2026-08-18T00:00:00Z",
        "meetings": [],  # would delete the evidence-bearing session
        "confirm_destructive": True,  # stored payload is overridden by the safe flow
    }
    repo = _FakePendencyRepo(
        {"pend-1": _pend_document("pend-1", course_id="poo", payload=json.dumps(payload))}
    )
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)

    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "aplicar_mudanca"},
            )
        )
    )

    assert result["status"] == 409
    assert result["body"]["error"] == "pendency_apply_conflict"
    assert result["body"]["destructive_sessions"] == 1
    assert repo.decisions == []
    assert store.commits == []  # the attended session is preserved, nothing deleted


def test_schedule_pendency_decision_update_storage_failure_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakePendencyRepo({"pend-1": _pend_document()})
    repo.update_error = StorageUnavailable("down")
    monkeypatch.setattr(function, "_pendency_repository", lambda _headers: repo)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/schedule/pendencies/pend-1/decision",
                body_json={"decision": "manter_atual"},
            )
        )
    )
    assert result["status"] == 503
    assert result["body"]["error"] == "pendency_store_unavailable"


def test_registration_draft_save_storage_failure_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    repo.save_error = StorageNotProvisioned("collection_not_found")
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)
    result = function.main(
        FakeContext(
            FakeRequest(
                "POST",
                "/v1/registration/drafts",
                body_json={
                    "course_id": "course-1",
                    "course_code": "DCC205",
                    "session_id": "s",
                    "form_data": {"a": 1},
                },
            )
        )
    )
    assert result["status"] == 503
    assert result["body"]["error"] == "draft_store_unavailable"


def test_registration_draft_delete_storage_failure_is_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _auth_ok(monkeypatch)
    repo = _FakeDraftRepo()
    repo.documents["draft-1"] = {"$id": "draft-1", "user_id": "user-1"}
    repo.delete_error = StorageUnavailable("down")
    monkeypatch.setattr(function, "_draft_repository", lambda _headers: repo)
    result = function.main(FakeContext(FakeRequest("DELETE", "/v1/registration/drafts/draft-1")))
    assert result["status"] == 503
    assert result["body"]["error"] == "draft_store_unavailable"
