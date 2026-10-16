"""Appwrite Function entrypoint for the Frequência UFMG API."""

import json
import re
import secrets
from collections.abc import Mapping
from contextvars import ContextVar
from os import environ
from pathlib import Path
from sys import path as module_search_path
from threading import Lock
from time import perf_counter, time
from typing import Any, cast

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

module_search_path.insert(0, str(Path(__file__).resolve().parent))
development_domain = Path(__file__).resolve().parents[2] / "backend" / "src"
module_search_path.insert(0, str(development_domain))

from academic_date_repository import (  # noqa: E402
    AcademicDateRepository,
    InvalidAcademicDate,
)
from attendance_service import InvalidAttendanceRequest, evaluate_attendance  # noqa: E402
from course_repository import (  # noqa: E402
    CourseRepository,
    DuplicateCourseCode,
    validate_course_id,
)
from course_service import InvalidCourse  # noqa: E402
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
from moodle_content_discovery import MoodleContentDiscoveryService  # noqa: E402
from moodle_date_import import MoodleDateImportService  # noqa: E402
from moodle_material import MoodleMaterialService  # noqa: E402
from moodle_material_catalog import MoodleMaterialCatalogService  # noqa: E402
from moodle_material_catalog_repository import (  # noqa: E402
    InvalidMoodleMaterialCatalog,
    MoodleMaterialCatalogRepository,
)
from moodle_mobile_capability import MoodleMobileCapabilityService  # noqa: E402
from moodle_structured_dates import (  # noqa: E402
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
)
from moodle_token_store import (  # noqa: E402
    AppwriteMoodleTokenStore,
    MoodleAuthorizationRequired,
    MoodleTokenCipher,
    MoodleTokenStoreUnavailable,
)
from overview_repository import (  # noqa: E402
    AcademicOverviewRepository,
    OverviewTooLarge,
)
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
from ufmg_auth import (  # noqa: E402
    InvalidUFMGCredentials,
    UFMGAuthenticationUnavailable,
    UFMGAuthenticator,
)
from ufmg_course_import import (  # noqa: E402
    InvalidUFMGEnrollmentResponse,
    UFMGCourseImportService,
    UFMGEnrollmentClient,
    UFMGEnrollmentUnavailable,
)
from ufmg_schedule_import import UFMGScheduleImportService  # noqa: E402
from ufmg_session_service import UFMGSessionService  # noqa: E402
from ufmg_session_store import (  # noqa: E402
    AppwriteUFMGSessionStore,
    InvalidUFMGSession,
    UFMGReauthenticationRequired,
    UFMGSessionCipher,
    UFMGSessionSecrets,
    UFMGSessionStoreUnavailable,
)
from ufmg_sync import UFMGSyncService  # noqa: E402

MAX_REQUEST_BYTES = 16_384
_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="")
_RESPONSE_STATUS: ContextVar[int] = ContextVar("response_status", default=200)
_REQUEST_METRICS: ContextVar["_RequestMetrics | None"] = ContextVar("request_metrics", default=None)
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


class _RequestMetrics:
    """Accumulate dependency counts safely across overview worker threads."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._reads = 0
        self._writes = 0
        self._failures = 0
        self._duration_ms = 0.0

    def record(self, _event: str, fields: Mapping[str, object]) -> None:
        with self._lock:
            if fields.get("kind") == "read":
                self._reads += 1
            else:
                self._writes += 1
            if fields.get("outcome") != "succeeded":
                self._failures += 1
            duration = fields.get("duration_ms")
            if isinstance(duration, int | float):
                self._duration_ms += duration

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "firestore_duration_ms": round(self._duration_ms, 3),
                "firestore_failures": self._failures,
                "firestore_reads": self._reads,
                "firestore_writes": self._writes,
            }


def main(context: Any) -> Any:
    """Dispatch one correlated request without making telemetry a dependency."""

    started = perf_counter()
    method = context.req.method.upper()
    path = context.req.path.rstrip("/") or "/"
    request_id = _validated_request_id(context.req.headers)
    metrics = _RequestMetrics()
    request_token = _REQUEST_ID.set(request_id)
    status_token = _RESPONSE_STATUS.set(200)
    metrics_token = _REQUEST_METRICS.set(metrics)
    try:
        result = _dispatch(context)
        _log(
            context,
            "request_completed",
            duration_ms=_elapsed_ms(started),
            method=method,
            request_id=request_id,
            route=_route_name(path),
            status=_RESPONSE_STATUS.get(),
            **metrics.snapshot(),
        )
        return result
    except Exception:
        _error(
            context,
            "request_failed",
            duration_ms=_elapsed_ms(started),
            method=method,
            request_id=request_id,
            route=_route_name(path),
            **metrics.snapshot(),
        )
        raise
    finally:
        _REQUEST_METRICS.reset(metrics_token)
        _RESPONSE_STATUS.reset(status_token)
        _REQUEST_ID.reset(request_token)


def _dispatch(context: Any) -> Any:
    """Apply bounded browser, payload, authentication, and route guards."""

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
                "Access-Control-Allow-Headers": (
                    "Authorization,Content-Type,X-Firebase-AppCheck,X-Request-ID"
                ),
                "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
                "Access-Control-Max-Age": "600",
            },
        )

    payload_error = _payload_error(headers, context.req.body_binary)
    if payload_error:
        status = 413 if payload_error == "payload_too_large" else 400
        _error(context, payload_error)
        return _respond(context, {"error": payload_error}, status, allowed_origin)

    if method == "GET" and path == "/v1/identity":
        return _identity(context, allowed_origin)
    if method == "POST" and path == "/v1/attendance/evaluate":
        return _attendance(context, allowed_origin)
    if method == "GET" and path == "/v1/overview":
        return _overview(context, allowed_origin)
    if method == "GET" and path == "/v1/courses":
        return _courses_list(context, allowed_origin)
    if method == "GET" and path == "/v1/moodle/dates":
        return _academic_dates(context, allowed_origin)
    if method == "GET" and path == "/v1/moodle/materials":
        return _moodle_material_catalog(context, allowed_origin)
    if path == "/v1/ufmg/session" and method in {"GET", "POST", "DELETE"}:
        return _ufmg_session(context, allowed_origin, method)
    if path == "/v1/ufmg/import/courses" and method == "POST":
        return _ufmg_course_import(context, allowed_origin)
    if path == "/v1/ufmg/import/schedules" and method == "POST":
        return _ufmg_schedule_import(context, allowed_origin)
    if path == "/v1/ufmg/import/dates" and method == "POST":
        return _moodle_date_import(context, allowed_origin)
    if path == "/v1/ufmg/discover/content" and method == "POST":
        return _moodle_content_discovery(context, allowed_origin)
    if path == "/v1/ufmg/moodle/capabilities" and method == "POST":
        return _moodle_mobile_capability(context, allowed_origin)
    if path == "/v1/ufmg/moodle/material-files" and method == "POST":
        return _moodle_material_files(context, allowed_origin)
    if path == "/v1/ufmg/sync" and method == "POST":
        return _ufmg_sync(context, allowed_origin)
    if path == "/v1/ufmg/sync/siga" and method == "POST":
        return _ufmg_sync(context, allowed_origin, siga_only=True)
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


def _ufmg_session(context: Any, origin: str | None, method: str) -> Any:
    user_id, rejected = _authentication(context, origin, f"/v1/ufmg/session/{method.lower()}")
    if rejected is not None:
        return rejected
    try:
        payload: Mapping[str, Any] = {}
        if method == "POST":
            raw_payload = context.req.body_json
            if (
                not isinstance(raw_payload, Mapping)
                or set(raw_payload) != {"username", "password"}
                or not isinstance(raw_payload["username"], str)
                or not isinstance(raw_payload["password"], str)
            ):
                raise InvalidUFMGSession
            payload = raw_payload
        service = _ufmg_session_service(context.req.headers)
        result: dict[str, Any]
        if method == "GET":
            result = service.status(cast(str, user_id), now=int(time()))
            event = "ufmg_session_status_succeeded"
        elif method == "POST":
            result = service.connect(
                cast(str, user_id),
                payload["username"],
                payload["password"],
                now=int(time()),
            )
            event = "ufmg_session_connect_succeeded"
        else:
            result = service.disconnect(cast(str, user_id))
            _moodle_token_store(context.req.headers).delete(cast(str, user_id))
            event = "ufmg_session_disconnect_succeeded"
    except InvalidUFMGCredentials as error:
        _error(context, "ufmg_credentials_invalid", reason=error.reason)
        return _respond(context, {"error": "ufmg_credentials_invalid"}, 401, origin)
    except UFMGAuthenticationUnavailable as error:
        return _ufmg_session_error(
            context,
            origin,
            "ufmg_authentication_unavailable",
            503,
            reason=error.reason,
        )
    except (UFMGSessionStoreUnavailable, MoodleTokenStoreUnavailable):
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except InvalidUFMGSession:
        return _ufmg_session_error(context, origin, "ufmg_session_rejected", 400)
    except ValueError:
        return _ufmg_session_error(context, origin, "ufmg_session_configuration_invalid", 503)
    _log(context, event)
    return _respond(context, result, origin=origin)


def _ufmg_course_import(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/ufmg/import/courses/post")
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "ufmg_course_import_rejected", 400)
    try:
        result = _ufmg_course_import_service(
            context.req.headers, cast(str, user_id)
        ).import_courses(cast(str, user_id), now=int(time()))
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except UFMGEnrollmentUnavailable as error:
        return _ufmg_session_error(
            context,
            origin,
            "ufmg_enrollment_unavailable",
            503,
            reason=error.reason,
            upstream_status=error.upstream_status,
        )
    except InvalidUFMGEnrollmentResponse:
        return _ufmg_session_error(context, origin, "ufmg_enrollment_invalid", 502)
    except UFMGSessionStoreUnavailable:
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (InvalidCourse, FirestoreRequestRejected, DuplicateCourseCode):
        return _course_error(context, origin, "course_import_rejected", 502)
    _log(context, "ufmg_course_import_succeeded", **result)
    return _respond(context, result, origin=origin)


def _ufmg_schedule_import(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/ufmg/import/schedules/post")
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "ufmg_schedule_import_rejected", 400)
    if environ.get("ENABLE_SCHEDULE_WRITES", "").lower() != "true":
        return _schedule_error(context, origin, "schedule_writes_disabled", 503)
    try:
        result = _ufmg_schedule_import_service(
            context.req.headers, cast(str, user_id)
        ).import_schedules(cast(str, user_id), now=int(time()))
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except UFMGEnrollmentUnavailable as error:
        return _ufmg_session_error(
            context,
            origin,
            "ufmg_enrollment_unavailable",
            503,
            reason=error.reason,
            upstream_status=error.upstream_status,
        )
    except InvalidUFMGEnrollmentResponse:
        return _ufmg_session_error(context, origin, "ufmg_enrollment_invalid", 502)
    except UFMGSessionStoreUnavailable:
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (InvalidSchedule, FirestoreRequestRejected, TypeError, ValueError):
        return _schedule_error(context, origin, "schedule_import_rejected", 502)
    _log(context, "ufmg_schedule_import_succeeded", **result)
    public_fields = (
        "total",
        "updated",
        "unchanged",
        "conflicts",
        "missing_courses",
        "meetings_imported",
    )
    return _respond(
        context,
        {field: result[field] for field in public_fields},
        origin=origin,
    )


def _ufmg_sync(context: Any, origin: str | None, *, siga_only: bool = False) -> Any:
    route = "/v1/ufmg/sync/siga/post" if siga_only else "/v1/ufmg/sync/post"
    user_id, rejected = _authentication(context, origin, route)
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "ufmg_sync_rejected", 400)
    if environ.get("ENABLE_SCHEDULE_WRITES", "").lower() != "true":
        return _schedule_error(context, origin, "schedule_writes_disabled", 503)
    try:
        service = _ufmg_sync_service(context.req.headers, cast(str, user_id))
        operation = service.sync_siga if siga_only else service.sync
        result = operation(cast(str, user_id), now=int(time()))
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except UFMGEnrollmentUnavailable as error:
        return _ufmg_session_error(
            context,
            origin,
            "ufmg_enrollment_unavailable",
            503,
            reason=error.reason,
            upstream_status=error.upstream_status,
        )
    except InvalidUFMGEnrollmentResponse:
        return _ufmg_session_error(context, origin, "ufmg_enrollment_invalid", 502)
    except MoodleUnavailable:
        return _ufmg_session_error(context, origin, "moodle_unavailable", 503)
    except InvalidMoodleResponse as error:
        return _ufmg_session_error(
            context, origin, "moodle_response_invalid", 502, reason=error.reason
        )
    except UFMGSessionStoreUnavailable:
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (
        DuplicateCourseCode,
        InvalidAcademicDate,
        InvalidCourse,
        InvalidSchedule,
        FirestoreRequestRejected,
        TypeError,
        ValueError,
    ):
        return _ufmg_session_error(context, origin, "ufmg_sync_rejected", 502)
    courses = cast(Mapping[str, int], result["courses"])
    schedules = cast(Mapping[str, int], result["schedules"])
    fields = {
        "course_created": courses["created"],
        "course_total": courses["total"],
        "schedule_conflicts": schedules["conflicts"],
        "schedule_total": schedules["total"],
        "schedule_updated": schedules["updated"],
    }
    if not siga_only:
        dates = cast(Mapping[str, int], result["dates"])
        fields.update(
            date_created=dates["created"],
            date_matched=dates["matched"],
            date_total=dates["total"],
            date_unmatched=dates["unmatched"],
        )
    _log(context, "ufmg_siga_sync_succeeded" if siga_only else "ufmg_sync_succeeded", **fields)
    return _respond(context, result, origin=origin)


def _moodle_date_import(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/ufmg/import/dates/post")
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "moodle_date_import_rejected", 400)
    try:
        result = _moodle_date_import_service(context.req.headers, cast(str, user_id)).import_dates(
            cast(str, user_id), now=int(time())
        )
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except MoodleUnavailable:
        return _ufmg_session_error(context, origin, "moodle_unavailable", 503)
    except InvalidMoodleResponse as error:
        return _ufmg_session_error(
            context, origin, "moodle_response_invalid", 502, reason=error.reason
        )
    except UFMGSessionStoreUnavailable:
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (
        InvalidAcademicDate,
        InvalidCourse,
        FirestoreRequestRejected,
        TypeError,
        ValueError,
    ):
        return _ufmg_session_error(context, origin, "moodle_date_import_rejected", 502)
    _log(context, "moodle_date_import_succeeded", **result)
    return _respond(context, result, origin=origin)


def _moodle_content_discovery(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/ufmg/discover/content/post")
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "moodle_content_discovery_rejected", 400)
    try:
        result = _moodle_content_discovery_service(
            context.req.headers, cast(str, user_id)
        ).discover(cast(str, user_id), now=int(time()))
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except MoodleUnavailable:
        return _ufmg_session_error(context, origin, "moodle_unavailable", 503)
    except InvalidMoodleResponse as error:
        return _ufmg_session_error(
            context, origin, "moodle_response_invalid", 502, reason=error.reason
        )
    except UFMGSessionStoreUnavailable:
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (
        InvalidCourse,
        InvalidMoodleMaterialCatalog,
        FirestoreRequestRejected,
        TypeError,
        ValueError,
    ):
        return _ufmg_session_error(context, origin, "moodle_content_discovery_rejected", 502)
    catalog = cast(Mapping[str, int], result["catalog"])
    _log(
        context,
        "moodle_content_discovery_succeeded",
        course_total=result["course_total"],
        candidate_total=result["candidate_total"],
        found=result["found"],
        empty=result["empty"],
        unmatched=result["unmatched"],
        ambiguous=result["ambiguous"],
        metaturma_candidates=result["metaturma_candidate_total"],
        catalog_created=catalog["created"],
        catalog_updated=catalog["updated"],
        catalog_unchanged=catalog["unchanged"],
        catalog_removed=catalog["removed"],
        catalog_writes=catalog["writes"],
    )
    return _respond(context, _legacy_moodle_content_payload(result), origin=origin)


def _legacy_moodle_content_payload(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the established discovery response stable for installed clients."""
    courses = []
    for raw_course in cast(list[Mapping[str, Any]], result["courses"]):
        course = dict(raw_course)
        course["candidates"] = [
            {
                key: value
                for key, value in candidate.items()
                if key != "moodle_course_id"
            }
            for candidate in cast(list[Mapping[str, Any]], course["candidates"])
        ]
        courses.append(course)
    return {
        key: courses if key == "courses" else value
        for key, value in result.items()
        if key != "catalog"
    }


def _moodle_material_catalog(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/moodle/materials")
    if rejected is not None:
        return rejected
    try:
        result = _moodle_material_catalog_service(
            context.req.headers, cast(str, user_id)
        ).list_catalog()
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    except (
        InvalidCourse,
        InvalidMoodleMaterialCatalog,
        FirestoreRequestRejected,
        TypeError,
        ValueError,
    ):
        return _ufmg_session_error(context, origin, "moodle_material_catalog_rejected", 502)
    _log(
        context,
        "moodle_material_catalog_listed",
        course_total=result["course_total"],
        candidate_total=result["candidate_total"],
        metaturma_candidates=result["metaturma_candidate_total"],
    )
    return _respond(context, result, origin=origin)


def _moodle_mobile_capability(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(
        context,
        origin,
        "/v1/ufmg/moodle/capabilities/post",
    )
    if rejected is not None:
        return rejected
    if not isinstance(context.req.body_json, Mapping) or context.req.body_json:
        return _ufmg_session_error(context, origin, "moodle_mobile_capability_rejected", 400)
    try:
        result = _moodle_mobile_capability_service(context.req.headers).probe(
            cast(str, user_id),
            now=int(time()),
        )
    except UFMGReauthenticationRequired:
        return _ufmg_session_error(context, origin, "ufmg_reauthentication_required", 401)
    except MoodleUnavailable:
        return _ufmg_session_error(context, origin, "moodle_unavailable", 503)
    except InvalidMoodleResponse as error:
        return _ufmg_session_error(
            context,
            origin,
            "moodle_response_invalid",
            502,
            reason=error.reason,
        )
    except (UFMGSessionStoreUnavailable, MoodleTokenStoreUnavailable):
        return _ufmg_session_error(context, origin, "ufmg_session_store_unavailable", 503)
    except (TypeError, ValueError):
        return _ufmg_session_error(context, origin, "moodle_mobile_capability_rejected", 502)
    _log(context, "moodle_mobile_capability_succeeded", **result)
    return _respond(context, result, origin=origin)


def _moodle_material_files(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(
        context,
        origin,
        "/v1/ufmg/moodle/material-files/post",
    )
    if rejected is not None:
        return rejected
    payload = context.req.body_json
    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"term", "course_id", "source_id"}
        or not isinstance(payload["term"], str)
        or re.fullmatch(r"20[2-9][0-9]-[12]", payload["term"]) is None
        or type(payload["course_id"]) is not int
        or not 1 <= payload["course_id"] <= 2_147_483_647
        or type(payload["source_id"]) is not int
        or not 1 <= payload["source_id"] <= 2_147_483_647
    ):
        return _ufmg_session_error(context, origin, "moodle_material_request_rejected", 400)
    try:
        result = _moodle_material_service(context.req.headers).list_files(
            cast(str, user_id),
            term=payload["term"],
            course_id=payload["course_id"],
            source_id=payload["source_id"],
            now=int(time()),
        )
    except MoodleAuthorizationRequired:
        return _ufmg_session_error(context, origin, "moodle_authorization_required", 401)
    except MoodleUnavailable:
        return _ufmg_session_error(context, origin, "moodle_unavailable", 503)
    except InvalidMoodleResponse as error:
        return _ufmg_session_error(
            context,
            origin,
            "moodle_response_invalid",
            502,
            reason=error.reason,
        )
    except (MoodleTokenStoreUnavailable, UFMGSessionStoreUnavailable):
        return _ufmg_session_error(context, origin, "moodle_token_store_unavailable", 503)
    except (TypeError, ValueError):
        return _ufmg_session_error(context, origin, "moodle_material_request_rejected", 400)
    _log(context, "moodle_material_files_succeeded", file_count=result["count"])
    return _respond(context, result, origin=origin)


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


def _academic_dates(context: Any, origin: str | None) -> Any:
    user_id, rejected = _authentication(context, origin, "/v1/moodle/dates")
    if rejected is not None:
        return rejected
    try:
        courses = _course_repository(context.req.headers, cast(str, user_id)).list_courses()
        repository = AcademicDateRepository(_firestore(context.req.headers, cast(str, user_id)))
        values = [
            {**item, "course_id": course["id"], "course_code": course["code"]}
            for course in courses
            for item in repository.list_dates(course["id"])
        ]
        if len(values) > 500:
            raise InvalidAcademicDate("too many academic dates")
        values.sort(key=lambda item: (item["due_at"], item["course_code"], item["id"]))
    except (InvalidAcademicDate, InvalidCourse, FirestoreRequestRejected, TypeError, ValueError):
        return _ufmg_session_error(context, origin, "academic_dates_invalid", 500)
    except FirestoreAccessDenied:
        return _course_error(context, origin, "course_access_denied", 403)
    except FirestoreUnavailable:
        return _course_error(context, origin, "course_store_unavailable", 503)
    _log(context, "academic_date_list_succeeded", count=len(values), course_count=len(courses))
    return _respond(context, {"dates": values}, origin=origin)


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


def _ufmg_session_service(headers: dict[str, str]) -> UFMGSessionService:
    return UFMGSessionService(UFMGAuthenticator(), _ufmg_session_store(headers))


def _ufmg_course_import_service(headers: dict[str, str], user_id: str) -> UFMGCourseImportService:
    return UFMGCourseImportService(
        _ufmg_session_store(headers),
        UFMGEnrollmentClient(),
        _course_repository(headers, user_id),
    )


def _ufmg_schedule_import_service(
    headers: dict[str, str], user_id: str
) -> UFMGScheduleImportService:
    return UFMGScheduleImportService(
        _ufmg_session_store(headers),
        UFMGEnrollmentClient(),
        _course_repository(headers, user_id),
        _schedule_repository(headers, user_id),
    )


def _ufmg_sync_service(headers: dict[str, str], user_id: str) -> UFMGSyncService:
    sessions = _ufmg_session_store(headers)
    enrollments = UFMGEnrollmentClient()
    courses = _course_repository(headers, user_id)
    schedules = _schedule_repository(headers, user_id)
    dates = _moodle_date_import_service(headers, user_id)
    return UFMGSyncService(
        sessions,
        enrollments,
        UFMGCourseImportService(sessions, enrollments, courses),
        UFMGScheduleImportService(sessions, enrollments, courses, schedules),
        dates,
    )


def _moodle_date_import_service(headers: dict[str, str], user_id: str) -> MoodleDateImportService:
    return MoodleDateImportService(
        _ufmg_session_store(headers),
        MoodleStructuredDatesClient(),
        _course_repository(headers, user_id),
        AcademicDateRepository(_firestore(headers, user_id)),
    )


def _moodle_content_discovery_service(
    headers: dict[str, str], user_id: str
) -> MoodleContentDiscoveryService:
    return MoodleContentDiscoveryService(
        _ufmg_session_store(headers),
        MoodleStructuredDatesClient(),
        _course_repository(headers, user_id),
        _moodle_material_catalog_repository(headers, user_id),
    )


def _moodle_material_catalog_service(
    headers: dict[str, str], user_id: str
) -> MoodleMaterialCatalogService:
    return MoodleMaterialCatalogService(
        _course_repository(headers, user_id),
        _moodle_material_catalog_repository(headers, user_id),
    )


def _moodle_material_catalog_repository(
    headers: dict[str, str], user_id: str
) -> MoodleMaterialCatalogRepository:
    return MoodleMaterialCatalogRepository(_firestore(headers, user_id))


def _moodle_mobile_capability_service(
    headers: dict[str, str],
) -> MoodleMobileCapabilityService:
    return MoodleMobileCapabilityService(
        _ufmg_session_store(headers),
        MoodleStructuredDatesClient(),
        _moodle_token_store(headers),
    )


def _moodle_material_service(headers: dict[str, str]) -> MoodleMaterialService:
    return MoodleMaterialService(
        _moodle_token_store(headers),
        MoodleStructuredDatesClient(),
    )


def _ufmg_session_store(headers: dict[str, str]) -> AppwriteUFMGSessionStore:
    endpoint = environ.get("APPWRITE_FUNCTION_API_ENDPOINT", "")
    project = environ.get("APPWRITE_FUNCTION_PROJECT_ID", "")
    database = environ.get("SECURITY_DATABASE_ID", "")
    table = environ.get("UFMG_SESSION_TABLE_ID", "")
    key = _header(headers, "x-appwrite-key")
    if not all((endpoint, project, database, table, key)):
        raise UFMGSessionStoreUnavailable("UFMG session store unavailable")
    secrets = UFMGSessionSecrets.from_environment(environ)
    client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
    store = AppwriteUFMGSessionStore(
        TablesDB(client),
        database_id=database,
        table_id=table,
        cipher=UFMGSessionCipher(
            secrets.encryption_keys,
            active_version=secrets.active_version,
        ),
        index_key=secrets.index_key,
    )
    return store


def _moodle_token_store(headers: dict[str, str]) -> AppwriteMoodleTokenStore:
    endpoint = environ.get("APPWRITE_FUNCTION_API_ENDPOINT", "")
    project = environ.get("APPWRITE_FUNCTION_PROJECT_ID", "")
    database = environ.get("SECURITY_DATABASE_ID", "")
    table = environ.get("UFMG_SESSION_TABLE_ID", "")
    key = _header(headers, "x-appwrite-key")
    if not all((endpoint, project, database, table, key)):
        raise UFMGSessionStoreUnavailable("UFMG session store unavailable")
    secrets = UFMGSessionSecrets.from_environment(environ)
    client = Client().set_endpoint(endpoint).set_project(project).set_key(key)
    return AppwriteMoodleTokenStore(
        TablesDB(client),
        database_id=database,
        table_id=table,
        cipher=MoodleTokenCipher(
            secrets.encryption_keys,
            active_version=secrets.active_version,
        ),
        index_key=secrets.index_key,
    )


def _firestore(headers: dict[str, str], user_id: str) -> FirestoreRestClient:
    metrics = _REQUEST_METRICS.get()

    return FirestoreRestClient(
        project_id=environ.get("FIREBASE_PROJECT_ID", ""),
        user_id=user_id,
        id_token=firebase_bearer_token(headers),
        telemetry=metrics.record if metrics is not None else None,
    )


def _course_error(context: Any, origin: str | None, error: str, status: int) -> Any:
    _error(context, error)
    return _respond(context, {"error": error}, status, origin)


def _ufmg_session_error(
    context: Any,
    origin: str | None,
    error: str,
    status: int,
    **log_fields: Any,
) -> Any:
    _error(context, error, **log_fields)
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
        "/v1/moodle/dates",
        "/v1/moodle/materials",
        "/v1/overview",
        "/v1/ufmg/session",
        "/v1/ufmg/import/courses",
        "/v1/ufmg/import/schedules",
        "/v1/ufmg/import/dates",
        "/v1/ufmg/discover/content",
        "/v1/ufmg/moodle/capabilities",
        "/v1/ufmg/moodle/material-files",
        "/v1/ufmg/sync",
        "/v1/ufmg/sync/siga",
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
    _RESPONSE_STATUS.set(status)
    headers = {
        "Cache-Control": "no-store",
        "Vary": "Origin",
        "X-Content-Type-Options": "nosniff",
        "X-Request-ID": _REQUEST_ID.get(),
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Expose-Headers"] = "X-Request-ID"
    if extra_headers:
        headers.update(extra_headers)
    return context.res.json(body, status, headers)


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


def _validated_request_id(headers: dict[str, str]) -> str:
    candidate = _header(headers, "x-request-id")
    if _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return f"request-{secrets.token_urlsafe(18)}"


def _route_name(path: str) -> str:
    if path in {
        "/v1/identity",
        "/v1/attendance/evaluate",
        "/v1/overview",
        "/v1/courses",
        "/v1/moodle/dates",
        "/v1/moodle/materials",
        "/v1/ufmg/session",
        "/v1/ufmg/import/courses",
        "/v1/ufmg/import/schedules",
        "/v1/ufmg/import/dates",
        "/v1/ufmg/discover/content",
        "/v1/ufmg/moodle/capabilities",
        "/v1/ufmg/moodle/material-files",
        "/v1/ufmg/sync",
        "/v1/ufmg/sync/siga",
    }:
        return path
    if _session_mutation_path(path) is not None:
        mutation = path.rsplit("/", 1)[-1]
        return f"/v1/courses/:course_id/sessions/:session_id/{mutation}"
    if path.startswith("/v1/courses/") and path.endswith("/schedule"):
        return "/v1/courses/:course_id/schedule"
    if path.startswith("/v1/courses/"):
        return "/v1/courses/:course_id"
    return "unmatched"


def _log(context: Any, event: str, **fields: Any) -> None:
    try:
        context.log(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))
    except Exception:
        _fallback_delivery(context.error, "log")


def _error(context: Any, event: str, **fields: Any) -> None:
    try:
        context.error(json.dumps({"event": event, **fields}, separators=(",", ":"), sort_keys=True))
    except Exception:
        _fallback_delivery(context.log, "error")


def _fallback_delivery(deliver: Any, sink: str) -> None:
    try:
        deliver(
            json.dumps(
                {"event": "observability_delivery_failed", "sink": sink},
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except Exception:
        return
