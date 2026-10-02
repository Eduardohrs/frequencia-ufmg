"""Appwrite Function entrypoint for the Python platform feasibility gate."""

import json
from os import environ
from pathlib import Path
from sys import path as module_search_path
from time import perf_counter
from typing import Any

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

module_search_path.insert(0, str(Path(__file__).resolve().parent))

from domain_probe import AttendanceStatus, calculate_absences  # noqa: E402
from firebase_identity import InvalidIdentity, verify_firebase_identity  # noqa: E402
from pdf_probe import extract_pdf_summary  # noqa: E402


def main(context: Any) -> Any:
    """Dispatch the three bounded probes exposed by the temporary function."""

    started = perf_counter()
    method = context.req.method.upper()
    path = context.req.path.rstrip("/") or "/"

    if method == "GET" and path == "/health":
        return _health(context, started)
    if method == "POST" and path == "/domain":
        return _domain(context, started)
    if method == "POST" and path == "/pdf":
        return _pdf(context, started)
    if method == "GET" and path == "/v1/identity":
        return _identity(context)
    return context.res.json({"error": "not_found"}, 404)


def _identity(context: Any) -> Any:
    try:
        _firebase_identity(context.req.headers)
    except InvalidIdentity:
        _error(context, "firebase_identity_rejected")
        return context.res.json({"error": "unauthorized"}, 401)

    _log(context, "firebase_identity_verified")
    return context.res.json({"authenticated": True})


def _firebase_identity(headers: dict[str, str]) -> str:
    identity = verify_firebase_identity(headers, environ.get("FIREBASE_PROJECT_ID", ""))
    return identity.uid


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
