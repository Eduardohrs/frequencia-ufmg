"""Appwrite Function entrypoint for the Python platform feasibility gate."""

import json
from os import environ
from pathlib import Path
from sys import path as module_search_path
from time import perf_counter, time
from typing import Any, cast

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

module_search_path.insert(0, str(Path(__file__).resolve().parent))

from domain_probe import AttendanceStatus, calculate_absences  # noqa: E402
from firebase_app_check import (  # noqa: E402
    FirebaseAppIdentity,
    InvalidAppCheck,
    verify_firebase_app_check,
)
from firebase_identity import InvalidIdentity, verify_firebase_identity  # noqa: E402
from pdf_probe import extract_pdf_summary  # noqa: E402
from quota_guard import (  # noqa: E402
    AppwriteSecurityStore,
    RateLimitExceeded,
    ReplayDetected,
    SecurityStoreUnavailable,
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
    if method == "OPTIONS" and path == "/v1/identity":
        return _respond(
            context,
            {},
            204,
            allowed_origin,
            {
                "Access-Control-Allow-Headers": (
                    "Authorization,Content-Type,X-Firebase-AppCheck"
                ),
                "Access-Control-Allow-Methods": "GET,OPTIONS",
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
    return _respond(context, {"error": "not_found"}, 404, allowed_origin)


def _identity(context: Any, origin: str | None) -> Any:
    now = int(time())
    try:
        user_id = _firebase_identity(context.req.headers)
    except InvalidIdentity:
        _error(context, "firebase_identity_rejected")
        return _respond(context, {"error": "unauthorized"}, 401, origin)

    try:
        app = _firebase_app(context.req.headers, now)
    except InvalidAppCheck:
        _error(context, "app_check_rejected")
        return _respond(context, {"error": "app_check_invalid"}, 401, origin)

    try:
        _security_store(context.req.headers).consume(
            token_digest=app.token_digest,
            user_id=user_id,
            route="/v1/identity",
            expires_at=app.expires_at,
            now=now,
        )
    except ReplayDetected:
        _error(context, "app_check_replayed")
        return _respond(context, {"error": "app_check_replayed"}, 409, origin)
    except RateLimitExceeded as error:
        _error(context, "rate_limit_exceeded")
        return _respond(
            context,
            {"error": "rate_limited"},
            429,
            origin,
            {"Retry-After": str(error.retry_after)},
        )
    except (SecurityStoreUnavailable, ValueError):
        _error(context, "security_guard_unavailable")
        return _respond(
            context,
            {"error": "security_guard_unavailable"},
            503,
            origin,
        )

    _log(context, "request_authenticated")
    return _respond(context, {"authenticated": True}, origin=origin)


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


def _error(context: Any, event: str) -> None:
    context.error(json.dumps({"event": event}, separators=(",", ":")))
