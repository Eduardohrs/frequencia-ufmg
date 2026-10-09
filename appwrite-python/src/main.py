"""Appwrite Function entrypoint for the Python platform feasibility gate."""

import json
from collections.abc import Mapping
from os import environ
from pathlib import Path
from sys import path as module_search_path
from time import perf_counter, time
from typing import Any, cast

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

module_search_path.insert(0, str(Path(__file__).resolve().parent))
development_domain = Path(__file__).resolve().parents[2] / "backend" / "src"
module_search_path.insert(0, str(development_domain))

from attendance_service import InvalidAttendanceRequest, evaluate_attendance  # noqa: E402
from course_repository import (  # noqa: E402
    CourseRepository,
    DuplicateCourseCode,
    validate_course_id,
)
from course_service import InvalidCourse  # noqa: E402
from domain_probe import AttendanceStatus, calculate_absences  # noqa: E402
from firebase_app_check import (  # noqa: E402
    FirebaseAppIdentity,
    InvalidAppCheck,
    verify_firebase_app_check,
)
from firebase_identity import (  # noqa: E402
    InvalidIdentity,
    firebase_bearer_token,
    verify_firebase_identity,
)
from firestore_rest import (  # noqa: E402
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreRestClient,
    FirestoreUnavailable,
)
from overview_repository import (  # noqa: E402
    AcademicOverviewRepository,
    OverviewTooLarge,
)
from pdf_probe import extract_pdf_summary  # noqa: E402
from quota_guard import (  # noqa: E402
    AppwriteSecurityStore,
    RateLimitExceeded,
    ReplayDetected,
    SecurityStoreUnavailable,
)
from schedule_repository import (  # noqa: E402
    DestructiveScheduleChange,
    ScheduleRepository,
)
from schedule_service import InvalidSchedule, ScheduleOverlap  # noqa: E402
from session_repository import SessionMutationRepository  # noqa: E402
from session_service import (  # noqa: E402
    InactiveAttendanceSession,
    InvalidSessionMutation,
)

MAX_REQUEST_BYTES = 16_384


def main(context: Any) -> Any:
    """Dispatch public routes through bounded browser and payload guards."""

    started = perf_counter()
    method = context.req.method.upper()
    path = context.req.path.rstrip("/") or "/"
    headers = context.req.headers
    origin = _header(headers, "origin")
    allowed_origin = _allowed_origin(origin)

    if origin and allowed_origin is None:
        _error(context, "origin_rejected")
        return _respond(context, {"error": "origin_forbidden"}, 403)
    if method == "OPTIONS" and _is_public_api_path(path):
        return _respond(
            context,
            {},
            204,
            allowed_origin,
            {
                "Access-Control-Allow-Headers": ("Authorization,Content-Type,X-Firebase-AppCheck"),
                "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
                "Access-Control-Max-Age": "600",
            },
        )

    payload_error = _payload_error(headers, context.req.body_binary)
    if payload_error:
        status = 413 if payload_error == "payload_too_large" else 400
        _error(context, payload_error)
        return _respond(context, {"error": payload_error}, status, allowed_origin)

    spike_enabled = environ.get("ENABLE_SPIKE_ROUTES", "").lower() == "true"
    if spike_enabled and method == "GET" and path == "/health":
        return _health(context, started)
    if spike_enabled and method == "POST" and path == "/domain":
        return _domain(context, started)
    if spike_enabled and method == "POST" and path == "/pdf":
        return _pdf(context, started)
    if method == "GET" and path == "/v1/identity":
        return _identity(context, allowed_origin)
    if method == "POST" and path == "/v1/attendance/evaluate":
        return _attendance(context, allowed_origin)
    if method == "GET" and path == "/v1/overview":
        return _overview(context, allowed_origin)
    if method == "GET" and path == "/v1/courses":
        return _courses_list(context, allowed_origin)
    session_mutation = _session_mutation_path(path)
    if method == "PUT" and session_mutation is not None:
        course_id, session_id, mutation = session_mutation
        return _session_mutation(
            context,
            allowed_origin,
            course_id,
            session_id,
            mutation,
        )
    if (
        path.startswith("/v1/courses/")
        and path.endswith("/schedule")
        and method
        in {
            "GET",
            "PUT",
        }
    ):
        course_id = path.removeprefix("/v1/courses/").removesuffix("/schedule")
        return _schedule(context, allowed_origin, method, course_id)
    if path.startswith("/v1/courses/") and method in {"PUT", "DELETE"}:
        return _course_mutation(context, allowed_origin, method, path.removeprefix("/v1/courses/"))
    return _respond(context, {"error": "not_found"}, 404, allowed_origin)


def _schedule(context: Any, origin: str | None, method: str, course_id: str) -> Any:
    user_id, rejected = _authentication(context, origin, f"/v1/courses/schedule/{method.lower()}")
    if rejected is not None:
        return rejected
    if method == "PUT" and environ.get("ENABLE_SCHEDULE_WRITES", "").lower() != "true":
        return _schedule_error(context, origin, "schedule_writes_disabled", 503)
    try:
        valid_id = validate_course_id(course_id)
        repository = _schedule_repository(context.req.headers, cast(str, user_id))
        result = (
            repository.get_schedule(valid_id)
            if method == "GET"
            else repository.save_schedule(valid_id, context.req.body_json)
        )
    except ScheduleOverlap:
        return _schedule_error(context, origin, "schedule_overlap", 409)
    except DestructiveScheduleChange as error:
        return _schedule_error(
            context,
            origin,
            "schedule_destructive_conflict",
            409,
            destructive_sessions=error.count,
        )
    except (InvalidSchedule, InvalidCourse, TypeError, ValueError):
        error_code = "schedule_data_invalid" if method == "GET" else "schedule_rejected"
        return _schedule_error(context, origin, error_code, 500 if method == "GET" else 400)
    except FirestoreRequestRejected:
        error_code = "schedule_data_invalid" if method == "GET" else "schedule_rejected"
        return _schedule_error(context, origin, error_code, 500 if method == "GET" else 400)
    except FirestoreNotFound:
        return _schedule_error(context, origin, "course_not_found", 404)
    except FirestoreAccessDenied:
        return _schedule_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _schedule_error(context, origin, "course_store_unavailable", 503)
    event = "schedule_preview_succeeded" if method == "GET" else "schedule_save_succeeded"
    _log(context, event, **result["changes"])
    return _respond(context, result, origin=origin)


def _identity(context: Any, origin: str | None) -> Any:
    _, rejected = _authentication(context, origin, "/v1/identity")
    if rejected is not None:
        return rejected
    _log(context, "request_authenticated")
    return _respond(context, {"authenticated": True}, origin=origin)


def _attendance(context: Any, origin: str | None) -> Any:
    _, rejected = _authentication(context, origin, "/v1/attendance/evaluate")
    if rejected is not None:
        return rejected
    try:
        result = evaluate_attendance(context.req.body_json)
    except (InvalidAttendanceRequest, TypeError, ValueError):
        _error(context, "attendance_rejected")
        return _respond(context, {"error": "invalid_request"}, 400, origin)
    _log(context, "attendance_evaluated")
    return _respond(context, result, origin=origin)


def _overview(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/overview")
    if rejected is not None:
        return rejected
    if environ.get("ENABLE_OVERVIEW_READS", "").lower() != "true":
        return _overview_error(context, origin, "overview_reads_disabled", 503)
    try:
        items = _overview_repository(context.req.headers, cast(str, user_id)).load()
    except OverviewTooLarge:
        return _overview_error(context, origin, "overview_too_large", 409)
    except (InvalidCourse, InvalidSchedule, FirestoreRequestRejected, TypeError, ValueError):
        return _overview_error(context, origin, "overview_data_invalid", 500)
    except FirestoreAccessDenied:
        return _overview_error(context, origin, "overview_access_denied", 403)
    except FirestoreUnavailable:
        return _overview_error(context, origin, "overview_store_unavailable", 503)
    _log(
        context,
        "overview_load_succeeded",
        course_count=len(items),
        session_count=sum(len(item["sessions"]) for item in items),
    )
    return _respond(context, {"items": items}, origin=origin)


def _session_mutation(
    context: Any,
    origin: str | None,
    course_id: str,
    session_id: str,
    mutation: str,
) -> Any:
    route = f"/v1/sessions/{mutation}/put"
    user_id, rejected = _authentication(context, origin, route)
    if rejected is not None:
        return rejected
    if environ.get("ENABLE_SESSION_WRITES", "").lower() != "true":
        return _session_error(context, origin, "session_writes_disabled", 503)
    try:
        repository = _session_repository(context.req.headers, cast(str, user_id))
        if mutation == "attendance":
            result = repository.save_attendance(
                course_id,
                session_id,
                context.req.body_json,
            )
            body = context.req.body_json
            _log(
                context,
                "attendance_save_succeeded",
                manual_correction=isinstance(body, Mapping) and "absences" in body,
            )
        else:
            result = repository.save_calendar_status(
                course_id,
                session_id,
                context.req.body_json,
            )
            _log(context, "calendar_status_save_succeeded")
    except InactiveAttendanceSession:
        return _session_error(context, origin, "attendance_inactive_session", 409)
    except (InvalidSessionMutation, InvalidCourse, TypeError, ValueError):
        return _session_error(context, origin, "session_mutation_rejected", 400)
    except (InvalidSchedule, FirestoreRequestRejected):
        return _session_error(context, origin, "session_data_invalid", 500)
    except FirestoreNotFound:
        return _session_error(context, origin, "session_not_found", 404)
    except FirestoreAccessDenied:
        return _session_error(context, origin, "session_access_denied", 403)
    except FirestoreUnavailable:
        return _session_error(context, origin, "session_store_unavailable", 503)
    return _respond(context, result, origin=origin)


def _authentication(
    context: Any,
    origin: str | None,
    route: str,
) -> tuple[str | None, Any | None]:
    now = int(time())
    try:
        user_id = _firebase_identity(context.req.headers)
    except InvalidIdentity:
        _error(context, "firebase_identity_rejected")
        return None, _respond(context, {"error": "unauthorized"}, 401, origin)

    try:
        app = _firebase_app(context.req.headers, now)
    except InvalidAppCheck as error:
        _error(context, "app_check_rejected", reason=error.reason)
        return None, _respond(context, {"error": "app_check_invalid"}, 401, origin)

    try:
        _security_store(context.req.headers).consume(
            token_digest=app.token_digest,
            user_id=user_id,
            route=route,
            expires_at=app.expires_at,
            now=now,
        )
    except ReplayDetected:
        _error(context, "app_check_replayed")
        return None, _respond(context, {"error": "app_check_replayed"}, 409, origin)
    except RateLimitExceeded as error:
        _error(context, "rate_limit_exceeded")
        return None, _respond(
            context,
            {"error": "rate_limited"},
            429,
            origin,
            {"Retry-After": str(error.retry_after)},
        )
    except (SecurityStoreUnavailable, ValueError):
        _error(context, "security_guard_unavailable")
        return None, _respond(
            context,
            {"error": "security_guard_unavailable"},
            503,
            origin,
        )

    return user_id, None


def _courses_list(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/courses")
    if rejected is not None:
        return rejected
    try:
        courses = _course_repository(context.req.headers, cast(str, user_id)).list_courses()
    except (InvalidCourse, FirestoreRequestRejected):
        return _course_error(context, origin, "course_data_invalid", 500)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    _log(context, "course_list_succeeded", count=len(courses))
    return _respond(context, {"courses": courses}, origin=origin)


def _course_mutation(context: Any, origin: str | None, method: str, course_id: str) -> Any:
    user_id, rejected = _authentication(context, origin, f"/v1/courses/{method.lower()}")
    if rejected is not None:
        return rejected
    try:
        valid_id = validate_course_id(course_id)
        repository = _course_repository(context.req.headers, cast(str, user_id))
        if method == "PUT":
            payload = {**context.req.body_json, "id": valid_id}
            course = repository.save_course(payload)
            _log(context, "course_save_succeeded")
            return _respond(context, {"course": course}, origin=origin)
        repository.delete_course(valid_id)
    except DuplicateCourseCode:
        return _course_error(context, origin, "course_code_conflict", 409)
    except (InvalidCourse, FirestoreRequestRejected, TypeError, ValueError):
        return _course_error(context, origin, "course_rejected", 400)
    except FirestoreNotFound:
        return _course_error(context, origin, "course_not_found", 404)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    _log(context, "course_delete_succeeded")
    return _respond(context, {"deleted": True}, origin=origin)


def _course_repository(headers: dict[str, str], user_id: str) -> CourseRepository:
    return CourseRepository(_firestore(headers, user_id))


def _schedule_repository(headers: dict[str, str], user_id: str) -> ScheduleRepository:
    return ScheduleRepository(_firestore(headers, user_id))


def _session_repository(headers: dict[str, str], user_id: str) -> SessionMutationRepository:
    return SessionMutationRepository(_firestore(headers, user_id))


def _overview_repository(headers: dict[str, str], user_id: str) -> AcademicOverviewRepository:
    return AcademicOverviewRepository(_firestore(headers, user_id))


def _firestore(headers: dict[str, str], user_id: str) -> FirestoreRestClient:
    return FirestoreRestClient(
        project_id=environ.get("FIREBASE_PROJECT_ID", ""),
        user_id=user_id,
        id_token=firebase_bearer_token(headers),
    )


def _course_error(context: Any, origin: str | None, error: str, status: int) -> Any:
    _error(context, error)
    return _respond(context, {"error": error}, status, origin)


def _overview_error(context: Any, origin: str | None, error: str, status: int) -> Any:
    _error(context, error)
    return _respond(context, {"error": error}, status, origin)


def _schedule_error(
    context: Any,
    origin: str | None,
    error: str,
    status: int,
    **fields: Any,
) -> Any:
    _error(context, error, **fields)
    return _respond(context, {"error": error, **fields}, status, origin)


def _session_error(context: Any, origin: str | None, error: str, status: int) -> Any:
    _error(context, error)
    return _respond(context, {"error": error}, status, origin)


def _session_mutation_path(path: str) -> tuple[str, str, str] | None:
    segments = path.strip("/").split("/")
    if (
        len(segments) == 6
        and segments[:2] == ["v1", "courses"]
        and segments[3] == "sessions"
        and segments[5] in {"attendance", "calendar-status"}
    ):
        mutation = "attendance" if segments[5] == "attendance" else "calendar_status"
        return segments[2], segments[4], mutation
    return None


def _is_public_api_path(path: str) -> bool:
    return path in {
        "/v1/identity",
        "/v1/attendance/evaluate",
        "/v1/courses",
        "/v1/overview",
    } or path.startswith("/v1/courses/")


def _firebase_identity(headers: dict[str, str]) -> str:
    identity = verify_firebase_identity(headers, environ.get("FIREBASE_PROJECT_ID", ""))
    return identity.uid


def _firebase_app(headers: dict[str, str], now: int) -> FirebaseAppIdentity:
    return verify_firebase_app_check(
        headers,
        project_number=environ.get("FIREBASE_PROJECT_NUMBER", ""),
        allowed_app_ids={
            value.strip()
            for value in environ.get("FIREBASE_APP_IDS", "").split(",")
            if value.strip()
        },
        now=now,
    )


def _security_store(headers: dict[str, str]) -> AppwriteSecurityStore:
    values = {
        "endpoint": environ.get("APPWRITE_FUNCTION_API_ENDPOINT"),
        "project": environ.get("APPWRITE_FUNCTION_PROJECT_ID"),
        "database": environ.get("SECURITY_DATABASE_ID"),
        "table": environ.get("SECURITY_TABLE_ID"),
        "key": _header(headers, "x-appwrite-key"),
    }
    if any(not value for value in values.values()):
        raise SecurityStoreUnavailable("security store unavailable")
    try:
        rate_limit = int(environ.get("RATE_LIMIT_PER_MINUTE", "20"))
    except ValueError:
        raise SecurityStoreUnavailable("security store unavailable") from None

    client = (
        Client()
        .set_endpoint(values["endpoint"])
        .set_project(values["project"])
        .set_key(values["key"])
    )
    return AppwriteSecurityStore(
        TablesDB(client),
        database_id=cast(str, values["database"]),
        table_id=cast(str, values["table"]),
        rate_limit=rate_limit,
        window_seconds=60,
    )


def _allowed_origin(origin: str) -> str | None:
    if not origin:
        return None
    configured = {
        value.strip()
        for value in environ.get("ALLOWED_ORIGINS", "").split(",")
        if value.strip().startswith("https://")
        or value.strip().startswith("http://localhost")
        or value.strip().startswith("http://127.0.0.1")
    }
    return origin if origin in configured else None


def _payload_error(headers: dict[str, str], body: bytes) -> str | None:
    declared = _header(headers, "content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError:
            return "invalid_content_length"
        if declared_size < 0:
            return "invalid_content_length"
        if declared_size > MAX_REQUEST_BYTES:
            return "payload_too_large"
    if len(body) > MAX_REQUEST_BYTES:
        return "payload_too_large"
    return None


def _header(headers: dict[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.lower() == name), "")


def _respond(
    context: Any,
    body: dict[str, Any],
    status: int = 200,
    origin: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = {
        "Cache-Control": "no-store",
        "Vary": "Origin",
        "X-Content-Type-Options": "nosniff",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    if extra_headers:
        headers.update(extra_headers)
    return context.res.json(body, status, headers)


def _health(context: Any, started: float) -> Any:
    try:
        value = _read_probe_value(context.req.headers)
    except Exception:
        _error(context, "database_probe_failed")
        return context.res.json({"error": "database_unavailable"}, 503)

    elapsed = _elapsed_ms(started)
    _log(context, "health_probe_completed", handler_ms=elapsed)
    return context.res.json(
        {
            "database": value,
            "handler_ms": elapsed,
            "runtime": _runtime_metadata(),
        }
    )


def _domain(context: Any, started: float) -> Any:
    try:
        body = context.req.body_json
        status = AttendanceStatus(body["status"])
        lessons = body["lessons"]
        calls = body["calls"]
        if type(lessons) is not int or type(calls) is not int:
            raise ValueError("integer fields required")
        absences = calculate_absences(status, lessons, calls)
    except (KeyError, TypeError, ValueError):
        _error(context, "domain_probe_rejected")
        return context.res.json({"error": "invalid_request"}, 400)

    elapsed = _elapsed_ms(started)
    _log(context, "domain_probe_completed", handler_ms=elapsed)
    return context.res.json({"absences": absences, "handler_ms": elapsed})


def _pdf(context: Any, started: float) -> Any:
    try:
        summary = extract_pdf_summary(context.req.body_binary)
    except Exception:
        _error(context, "pdf_probe_rejected")
        return context.res.json({"error": "invalid_pdf"}, 400)

    elapsed = _elapsed_ms(started)
    _log(
        context,
        "pdf_probe_completed",
        bytes=summary.get("bytes"),
        handler_ms=elapsed,
        pages=summary.get("pages"),
    )
    return context.res.json({"handler_ms": elapsed, "summary": summary})


def _read_probe_value(headers: dict[str, str]) -> str:
    values = {
        "endpoint": environ.get("APPWRITE_FUNCTION_API_ENDPOINT"),
        "project": environ.get("APPWRITE_FUNCTION_PROJECT_ID"),
        "database": environ.get("SPIKE_DATABASE_ID"),
        "table": environ.get("SPIKE_TABLE_ID"),
        "row": environ.get("SPIKE_ROW_ID"),
        "key": {key.lower(): value for key, value in headers.items()}.get("x-appwrite-key"),
    }
    if any(not value for value in values.values()):
        raise RuntimeError("runtime configuration missing")

    client = (
        Client()
        .set_endpoint(values["endpoint"])
        .set_project(values["project"])
        .set_key(values["key"])
    )
    row = TablesDB(client).get_row(values["database"], values["table"], values["row"])
    value = row.data.get("value")
    if not isinstance(value, str):
        raise RuntimeError("invalid probe row")
    return value


def _runtime_metadata() -> dict[str, str | None]:
    return {
        "cpus": environ.get("APPWRITE_FUNCTION_CPUS"),
        "memory_mb": environ.get("APPWRITE_FUNCTION_MEMORY"),
        "region": environ.get("APPWRITE_FUNCTION_REGION"),
        "runtime": environ.get("APPWRITE_FUNCTION_RUNTIME_NAME"),
        "runtime_version": environ.get("APPWRITE_FUNCTION_RUNTIME_VERSION"),
    }


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


def _log(context: Any, event: str, **fields: Any) -> None:
    context.log(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))


def _error(context: Any, event: str, **fields: Any) -> None:
    context.error(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))
