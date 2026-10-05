import json
from dataclasses import dataclass, field
from typing import Any

import pytest

import main as function
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
from quota_guard import RateLimitExceeded, ReplayDetected, SecurityStoreUnavailable
from schedule_repository import DestructiveScheduleChange
from schedule_service import InvalidSchedule, ScheduleOverlap


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


def test_health_reads_tablesdb_and_reports_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")
    monkeypatch.setattr(function, "_read_probe_value", lambda _headers: "ready")
    monkeypatch.setenv("APPWRITE_FUNCTION_REGION", "nyc")
    context = FakeContext(FakeRequest("GET", "/health"))

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["database"] == "ready"
    assert result["body"]["runtime"]["region"] == "nyc"
    assert result["body"]["handler_ms"] >= 0
    assert json.loads(context.logs[0])["event"] == "health_probe_completed"


def test_health_sanitizes_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")

    def fail(_headers: dict[str, str]) -> str:
        raise RuntimeError("secret-token")

    monkeypatch.setattr(function, "_read_probe_value", fail)
    context = FakeContext(FakeRequest("GET", "/health"))

    result = function.main(context)

    assert result["body"] == {"error": "database_unavailable"}
    assert result["status"] == 503
    assert context.errors == ['{"event":"database_probe_failed"}']
    assert "secret-token" not in "".join(context.errors)


def test_domain_route_calculates_absences(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")
    context = FakeContext(
        FakeRequest(
            "POST",
            "/domain",
            body_json={"status": "saiu_mais_cedo", "lessons": 4, "calls": 2},
        )
    )

    result = function.main(context)

    assert result["status"] == 200
    assert result["body"]["absences"] == 2
    assert json.loads(context.logs[0])["event"] == "domain_probe_completed"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "unknown", "lessons": 2, "calls": 1},
        {"status": "presente"},
        {"status": "presente", "lessons": "2", "calls": 1},
    ],
)
def test_domain_route_rejects_invalid_payload(
    body: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")
    context = FakeContext(FakeRequest("POST", "/domain", body_json=body))

    result = function.main(context)
    assert result["body"] == {"error": "invalid_request"}
    assert result["status"] == 400
    assert context.errors == ['{"event":"domain_probe_rejected"}']


def test_pdf_route_returns_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")
    monkeypatch.setattr(function, "extract_pdf_summary", lambda _payload: {"pages": 1})
    context = FakeContext(FakeRequest("POST", "/pdf", body_binary=b"%PDF-test"))

    result = function.main(context)

    assert result["body"]["summary"] == {"pages": 1}
    assert json.loads(context.logs[0])["event"] == "pdf_probe_completed"


def test_pdf_route_sanitizes_invalid_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SPIKE_ROUTES", "true")

    def fail(_payload: bytes) -> dict[str, int]:
        raise ValueError("contains private academic content")

    monkeypatch.setattr(function, "extract_pdf_summary", fail)
    context = FakeContext(FakeRequest("POST", "/pdf", body_binary=b"private"))

    result = function.main(context)
    assert result["body"] == {"error": "invalid_pdf"}
    assert result["status"] == 400
    assert context.errors == ['{"event":"pdf_probe_rejected"}']
    assert "private academic content" not in "".join(context.errors)


def test_unknown_route_returns_not_found() -> None:
    context = FakeContext(FakeRequest("GET", "/unknown"))

    result = function.main(context)
    assert result["body"] == {"error": "not_found"}
    assert result["status"] == 404


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
    assert "private-token" not in "".join(context.errors)


def test_spike_routes_are_private_by_default() -> None:
    result = function.main(FakeContext(FakeRequest("GET", "/health")))

    assert result["status"] == 404


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
    assert result["headers"]["Vary"] == "Origin"


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


def test_read_probe_value_uses_injected_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

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

    class FakeRow:
        data = {"value": "ready"}

    class FakeTablesDB:
        def __init__(self, client: FakeClient) -> None:
            calls["client"] = client

        def get_row(self, database_id: str, table_id: str, row_id: str) -> FakeRow:
            calls["row"] = (database_id, table_id, row_id)
            return FakeRow()

    monkeypatch.setattr(function, "Client", FakeClient)
    monkeypatch.setattr(function, "TablesDB", FakeTablesDB)
    monkeypatch.setattr(
        function,
        "environ",
        {
            "APPWRITE_FUNCTION_API_ENDPOINT": "https://nyc.cloud.appwrite.io/v1",
            "APPWRITE_FUNCTION_PROJECT_ID": "project",
            "SPIKE_DATABASE_ID": "database",
            "SPIKE_TABLE_ID": "table",
            "SPIKE_ROW_ID": "row",
        },
    )

    value = function._read_probe_value({"x-appwrite-key": "ephemeral"})

    assert value == "ready"
    assert calls["row"] == ("database", "table", "row")
    assert calls["key"] == "ephemeral"

    FakeRow.data = {"value": None}
    with pytest.raises(RuntimeError, match="invalid probe row"):
        function._read_probe_value({"X-Appwrite-Key": "ephemeral"})


def test_read_probe_value_requires_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(function, "environ", {})

    with pytest.raises(RuntimeError, match="runtime configuration missing"):
        function._read_probe_value({})
