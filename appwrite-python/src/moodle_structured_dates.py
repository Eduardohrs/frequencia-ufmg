"""Read bounded, structured Moodle calendar data through the UFMG SSO session."""

import json
import re
import unicodedata
from base64 import b64decode
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from hashlib import md5, sha256
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from secrets import token_hex
from threading import Lock
from time import perf_counter
from typing import Any, Final, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from diario_teaching_plan import TeachingPlanParseError, parse_teaching_plan_html
from moodle_activities import InvalidActivityPage, parse_activity_page, plain_activity_text
from sync_timing import Telemetry, _emit, timed_stage
from ufmg_session_store import UFMGReauthenticationRequired

MAX_RESPONSE_BYTES = 1_048_576
CALENDAR_BATCH_MONTHS = 2
MAX_EVENTS = 500
MAX_MONTHS = 12
MAX_COURSES = 50
MAX_CANDIDATES = 500
MAX_DIARIO_BYTES = 20 * 1_048_576
MOODLE_ORIGIN = "https://virtual.ufmg.br"
# Per-sync in-memory memo bounds.  One client instance serves one authenticated
# sync request, and every key includes the session-token digest and term, so a
# cached entry can never leak across users, sessions or terms.
MAX_DISCOVERY_CACHE_ENTRIES = 4_096
MAX_ACTIVITY_PAGE_CACHE = 500
_SESSKEY = re.compile(rb'"sesskey"\s*:\s*"([A-Za-z0-9_-]{8,128})"')
_MOBILE_TOKEN = re.compile(r"[A-Za-z0-9]{16,256}")
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class InvalidMoodleResponse(Exception):
    """Moodle or the identity provider returned an unsafe/unexpected shape."""

    def __init__(
        self, reason: str = "unknown", *, details: dict[str, object] | None = None
    ) -> None:
        self.reason = reason if re.fullmatch(r"[a-z_]{1,64}", reason) else "unknown"
        self.details = details or {}
        super().__init__("invalid Moodle response")


class MoodleUnavailable(Exception):
    """The structured Moodle source could not be reached."""

    def __init__(
        self, message: str = "Moodle is unavailable", *,
        upstream_status: int | None = None,
        timed_out: bool = False,
    ) -> None:
        self.upstream_status = upstream_status
        self.timed_out = timed_out
        super().__init__(message)


@dataclass(frozen=True)
class MoodleMobileAuthorization:
    """Sensitive mobile credentials plus their non-secret capability summary."""

    webservice_token: str
    private_token: str | None
    direct_download_supported: bool
    download_files: bool
    private_file_access: bool

    def safe_capabilities(self) -> dict[str, bool]:
        return {
            "direct_download_supported": self.direct_download_supported,
            "download_files": self.download_files,
            "private_file_access": self.private_file_access,
            "webservice_token_issued": True,
        }


@dataclass(frozen=True)
class DiarioPlanProbe:
    """Non-sensitive facts proving that a Moodle plan resolves to a UFMG PDF."""

    delivery: str
    content_length: int
    format: str = "pdf"

    def safe_result(self) -> dict[str, object]:
        return {
            "available": True,
            "delivery": self.delivery,
            "format": self.format,
            "content_length": self.content_length,
        }


class _Response(Protocol):
    headers: Any

    def read(self, limit: int) -> bytes: ...

    def geturl(self) -> str: ...

    def __enter__(self) -> "_Response": ...

    def __exit__(self, *args: object) -> None: ...


class _Opener(Protocol):
    def open(self, request: Request, *, timeout: float) -> _Response: ...


class MoodleStructuredDatesClient:
    """Complete SAML without exposing cookies and read Moodle's calendar API."""

    # Moodle's authenticated ``core_course_get_contents`` export is the
    # authoritative course-wide activity payload we can read in one request.
    # It includes the activity description, dates and module files.  It does
    # not include the current student's submission state, so that field is
    # deliberately persisted as ``unknown`` until an explicit activity detail
    # read is requested.  Submission state is read through the assignment
    # submissions service when the module response omits it, so a missing
    # optional description or attachment never forces an HTML crawl.
    bulk_activity_details_complete = True

    def __init__(
        self,
        *,
        opener: _Opener | None = None,
        timeout_seconds: float = 12,
        telemetry: Telemetry | None = None,
        calendar_workers: int = 1,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("invalid Moodle timeout")
        if not 1 <= calendar_workers <= 4:
            raise ValueError("invalid calendar concurrency")
        self._timeout = timeout_seconds
        self._telemetry = telemetry
        self._calendar_workers = calendar_workers
        self._jar: CookieJar | None
        if opener is None:
            jar = CookieJar()
            jar.set_cookie(_ltpa_cookie_placeholder())
            self._jar = jar
            self._opener: _Opener = build_opener(HTTPCookieProcessor(jar))
        else:
            self._jar = None
            self._opener = opener
        self._connection_token_digest: bytes | None = None
        self._connections: dict[str, tuple[str, str, str]] = {}
        self._connection_count = 0
        self._connection_lock = Lock()
        self._request_sequence = 0
        self._request_lock = Lock()
        # Per-sync memo tables keyed by (token digest, term[, course id]).  They
        # let the material catalog and the activity index share one enrolled
        # course list and one course-state batch inside a single sync run.
        self._discovery_lock = Lock()
        self._enrolled_cache: dict[tuple[bytes, str], list[dict[str, object]]] = {}
        self._state_cache: dict[tuple[bytes, str, int], dict[str, list[dict[str, object]]]] = {}
        self._activity_page_cache: dict[tuple[bytes, str, int, str], dict[str, object]] = {}

    @property
    def connection_count(self) -> int:
        """Return the number of successful SAML exchanges made by this client."""

        return self._connection_count

    def fetch(
        self,
        token: str,
        *,
        term: str,
        months: list[tuple[int, int]],
    ) -> list[dict[str, str]]:
        _validate_inputs(token, months)
        root, ajax_path, sesskey = self._connect(token, term)
        # One ajax call per small batch keeps each response below
        # MAX_RESPONSE_BYTES instead of failing the whole term at once.
        events: dict[str, dict[str, str]] = {}
        chunks = [
            months[start : start + CALENDAR_BATCH_MONTHS]
            for start in range(0, len(months), CALENDAR_BATCH_MONTHS)
        ]

        def fetch_chunk(chunk: list[tuple[int, int]]) -> list[dict[str, str]]:
            calls = [
                {
                    "index": index,
                    "methodname": "core_calendar_get_calendar_monthly_view",
                    "args": {
                        "year": year,
                        "month": month,
                        "courseid": 1,
                        "categoryid": 0,
                        "includenavigation": False,
                        "mini": False,
                        "day": 1,
                    },
                }
                for index, (year, month) in enumerate(chunk)
            ]
            payload = self._ajax(root, ajax_path, sesskey, calls)
            return timed_stage(
                "moodle_calendar_batch_parse",
                partial(_parse_calendar, payload, len(calls)),
                telemetry=self._telemetry,
                fields={
                    "term": term,
                    "month_start": list(chunk[0]),
                    "month_count": len(chunk),
                    "response_bytes": len(payload),
                    "consumer": "academic_dates_and_agenda",
                },
            )

        if self._calendar_workers == 1 or len(chunks) <= 1:
            parsed_batches = [fetch_chunk(chunk) for chunk in chunks]
        else:
            worker_count = min(self._calendar_workers, len(chunks))
            with ThreadPoolExecutor(
                max_workers=worker_count, thread_name_prefix="moodle-calendar"
            ) as pool:
                futures = [pool.submit(fetch_chunk, chunk) for chunk in chunks]
                # Preserve deterministic conflict handling and event ordering
                # even though the HTTP batches complete independently.
                parsed_batches = [future.result() for future in futures]

        for parsed in parsed_batches:
            for event in parsed:
                previous = events.get(event["source_id"])
                if previous is not None and previous != event:
                    raise InvalidMoodleResponse("calendar_event_conflict")
                events[event["source_id"]] = event
        return sorted(events.values(), key=lambda item: (item["due_at"], item["source_id"]))

    def discover(
        self,
        token: str,
        *,
        term: str,
        course_codes: list[str],
        activities: bool = False,
        include_activities: bool = False,
    ) -> list[dict[str, object]]:
        """Discover bounded visible course resources without downloading content.

        ``include_activities`` lets the full academic sync reuse the activity
        index that was already parsed for the material catalog.  The default
        remains unchanged for callers that only need material candidates.
        """

        codes = _validate_course_codes(token, course_codes)
        root, ajax_path, sesskey = self._connect(token, term)
        digest = _token_digest(token)
        courses, enrolled_hit = self._enrolled_courses(
            digest, term, root, ajax_path, sesskey, requested=len(codes)
        )
        matched: list[tuple[str, dict[str, object], str]] = []
        results: dict[str, dict[str, object]] = {}
        for code in codes:
            matches = [course for course in courses if _course_matches(code, course)]
            canonical = [course for course in matches if not _is_metaturma(course)]
            if len(canonical) == 1:
                results[code] = {
                    "course_code": code,
                    "moodle_course_id": str(canonical[0]["id"]),
                    "status": "empty",
                    "candidates": [],
                }
                matched.append((code, canonical[0], "canonical"))
                matched.extend(
                    (code, course, "metaturma") for course in matches if _is_metaturma(course)
                )
            else:
                results[code] = {
                    "course_code": code,
                    "moodle_course_id": None,
                    "status": "ambiguous" if matches else "unmatched",
                    "candidates": [],
                }

        if matched:
            course_ids = [int(str(course["id"])) for _, course, _ in matched]
            states, hits, misses = self._course_states(
                digest, term, root, ajax_path, sesskey, course_ids
            )
            _emit(
                self._telemetry,
                "moodle_discovery_cache",
                {
                    "term": term,
                    "consumer": "activity_index" if activities else "material_catalog",
                    "enrolled_hit": enrolled_hit,
                    "state_hits": hits,
                    "state_misses": misses,
                    "course_count": len(codes),
                },
            )
            total = 0
            activity_totals: dict[str, int] = defaultdict(int)
            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            grouped_activities: dict[str, list[dict[str, object]]] = defaultdict(list)
            for (code, course, origin), state in zip(matched, states, strict=True):
                candidates = state["activities" if activities else "materials"]
                total += len(candidates)
                if total > MAX_CANDIDATES:
                    raise InvalidMoodleResponse("candidate_limit")
                grouped[code].extend(
                    candidate | {"origin": origin, "moodle_course_id": str(course["id"])}
                    for candidate in candidates
                )
                if include_activities and not activities:
                    activity_candidates = state["activities"]
                    activity_totals[code] += len(activity_candidates)
                    if activity_totals[code] > MAX_CANDIDATES:
                        raise InvalidMoodleResponse("activity_candidate_limit")
                    grouped_activities[code].extend(
                        candidate | {"origin": origin, "moodle_course_id": str(course["id"])}
                        for candidate in activity_candidates
                    )
            for code, candidates in grouped.items():
                result: dict[str, object] = {
                    "course_code": code,
                    "moodle_course_id": results[code]["moodle_course_id"],
                    "status": "found" if candidates else "empty",
                    "candidates": candidates,
                }
                if include_activities and not activities:
                    result["activity_candidates"] = grouped_activities.get(code, [])
                results[code] = result
        return [results[code] for code in codes]

    def discover_with_activities(
        self, token: str, *, term: str, course_codes: list[str]
    ) -> list[dict[str, object]]:
        """Discover material and activity indexes in the same state response."""

        return self.discover(
            token,
            term=term,
            course_codes=course_codes,
            include_activities=True,
        )

    def _enrolled_courses(
        self,
        digest: bytes,
        term: str,
        root: str,
        ajax_path: str,
        sesskey: str,
        *,
        requested: int,
    ) -> tuple[list[dict[str, object]], bool]:
        """Return the term's enrolled course list, memoized for this sync run."""
        key = (digest, term)
        with self._discovery_lock:
            cached = self._enrolled_cache.get(key)
        if cached is not None:
            return cached, True
        course_call = [
            {
                "index": 0,
                "methodname": "core_course_get_enrolled_courses_by_timeline_classification",
                "args": {
                    "classification": "all",
                    "limit": 100,
                    "offset": 0,
                    "sort": "fullname ASC",
                },
            }
        ]
        course_payload = self._ajax(root, ajax_path, sesskey, course_call)
        courses = timed_stage(
            "moodle_course_list_parse",
            lambda: _parse_course_list(course_payload),
            telemetry=self._telemetry,
            fields={
                "term": term,
                "course_count": requested,
                "response_bytes": len(course_payload),
                "consumer": "course_linking_and_material_catalog",
            },
        )
        with self._discovery_lock:
            if len(self._enrolled_cache) < MAX_DISCOVERY_CACHE_ENTRIES:
                self._enrolled_cache[key] = courses
        return courses, False

    def _course_states(
        self,
        digest: bytes,
        term: str,
        root: str,
        ajax_path: str,
        sesskey: str,
        course_ids: list[int],
    ) -> tuple[list[dict[str, list[dict[str, object]]]], int, int]:
        """Return per-course states (both material and activity views).

        Only uncached course ids are requested, in one batched AJAX call, so
        the material catalog and the activity index share a single
        ``core_courseformat_get_state`` batch per Moodle course per sync run.
        """
        states: list[dict[str, list[dict[str, object]]] | None] = [None] * len(course_ids)
        hits = 0
        missing: list[tuple[int, int]] = []
        with self._discovery_lock:
            for position, course_id in enumerate(course_ids):
                cached = self._state_cache.get((digest, term, course_id))
                if cached is not None:
                    states[position] = cached
                    hits += 1
                else:
                    missing.append((position, course_id))
        if missing:
            state_calls = [
                {
                    "index": index,
                    "methodname": "core_courseformat_get_state",
                    "args": {"courseid": course_id},
                }
                for index, (_, course_id) in enumerate(missing)
            ]
            state_payload = self._ajax(root, ajax_path, sesskey, state_calls)
            parsed = timed_stage(
                "moodle_course_state_parse",
                lambda: _parse_course_states_full(state_payload, root, len(missing)),
                telemetry=self._telemetry,
                fields={
                    "term": term,
                    "course_count": len(missing),
                    "response_bytes": len(state_payload),
                    "include_activities": True,
                    "consumer": "material_catalog_and_activity_index",
                    "cache_hits": hits,
                },
            )
            with self._discovery_lock:
                for (position, course_id), state in zip(missing, parsed, strict=True):
                    states[position] = state
                    if len(self._state_cache) < MAX_DISCOVERY_CACHE_ENTRIES:
                        self._state_cache[(digest, term, course_id)] = state
        return cast(list[dict[str, list[dict[str, object]]]], states), hits, len(missing)

    def _clear_discovery_caches(self) -> None:
        """Drop per-sync memos when the session token changes."""
        with self._discovery_lock:
            self._enrolled_cache.clear()
            self._state_cache.clear()
            self._activity_page_cache.clear()

    def list_activities(
        self, token: str, *, term: str, course_id: int, course_code: str | None = None
    ) -> list[dict[str, object]]:
        if type(course_id) is not int or not 1 <= course_id <= 2_147_483_647:
            raise InvalidMoodleResponse("activity_course_id")
        if course_code is not None:
            discovered = self.discover(
                token, term=term, course_codes=[course_code], activities=True
            )[0]
            if discovered["status"] not in {"found", "empty"}:
                raise InvalidMoodleResponse("course_activity_link_" + str(discovered["status"]))
            candidates = discovered["candidates"]
            if not isinstance(candidates, list):
                raise InvalidMoodleResponse("course_activity_index_shape")
            return candidates
        root, ajax_path, sesskey = self._connect(token, term)
        digest = _token_digest(token)
        states, hits, misses = self._course_states(
            digest, term, root, ajax_path, sesskey, [course_id]
        )
        _emit(
            self._telemetry,
            "moodle_discovery_cache",
            {
                "term": term,
                "consumer": "activity_snapshot_index",
                "enrolled_hit": False,
                "state_hits": hits,
                "state_misses": misses,
                "course_count": 1,
            },
        )
        return states[0]["activities"]

    def activity_updates_since(
        self,
        token: str,
        *,
        term: str,
        course_id: int,
        since: int,
    ) -> set[int]:
        """Return course-module ids changed in Moodle since the last snapshot.

        Moodle exposes this through the same authenticated AJAX service used for
        the course index.  It is deliberately a change detector: it does not
        return activity bodies, so callers still choose one bulk read only when
        a module actually changed.
        """

        if type(course_id) is not int or not 1 <= course_id <= 2_147_483_647:
            raise InvalidMoodleResponse("activity_updates_course_id")
        if type(since) is not int or since < 0:
            raise InvalidMoodleResponse("activity_updates_since")
        root, ajax_path, sesskey = self._connect(token, term)
        calls = [
            {
                "index": 0,
                "methodname": "core_course_get_updates_since",
                "args": {"courseid": course_id, "since": since, "filter": []},
            }
        ]
        payload = self._ajax(root, ajax_path, sesskey, calls)
        return timed_stage(
            "moodle_activity_updates_parse",
            lambda: _parse_activity_updates(payload),
            telemetry=self._telemetry,
            fields={
                "term": term,
                "moodle_course_id": course_id,
                "response_bytes": len(payload),
                "consumer": "activity_snapshot_change_detection",
            },
        )

    def fetch_course_activity_bulk(
        self,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        course_id: int,
    ) -> dict[str, dict[str, object]]:
        """Read all visible assignment/quiz details in one Moodle request.

        ``core_course_get_contents`` already returns every visible module,
        descriptions, activity dates and module files.  The old implementation
        requested one HTML page per assignment; this method keeps the same
        persisted shape while replacing that N+1 network pattern with one
        course-level REST call.
        """

        _validate_mobile_tokens(webservice_token, private_token, course_id)
        root = _moodle_root(term)
        path = f"{root}/webservice/rest/server.php"
        payload, final_url, content_type = self._open(
            Request(
                f"{MOODLE_ORIGIN}{path}",
                data=urlencode(
                    {
                        "moodlewsrestformat": "json",
                        "moodlewssettingfileurl": "1",
                        "moodlewssettingfilter": "1",
                        "wsfunction": "core_course_get_contents",
                        "wstoken": webservice_token,
                        "courseid": str(course_id),
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
        )
        _require_json_endpoint(final_url, content_type, path)
        return timed_stage(
            "moodle_activity_bulk_parse",
            lambda: _parse_course_activity_contents(payload, root=root),
            telemetry=self._telemetry,
            fields={
                "term": term,
                "moodle_course_id": course_id,
                "response_bytes": len(payload),
                "consumer": "activity_snapshot_details",
            },
        )

    def fetch_course_activity_module_bulk(
        self,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        course_id: int,
        kind: str,
    ) -> dict[str, dict[str, object]]:
        """Read one activity type through Moodle's official mobile bulk API.

        ``core_course_get_contents`` is a useful index, but UFMG's response
        omits the description/attachment fields for some modules.  Moodle's
        type-specific mobile functions expose those fields in one course
        response, avoiding one HTML request per activity.  If the installation
        does not expose a function, callers retain the existing HTML fallback.
        """

        _validate_mobile_tokens(webservice_token, private_token, course_id)
        if kind not in {"assign", "quiz"}:
            raise InvalidMoodleResponse("activity_module_kind")
        root = _moodle_root(term)
        path = f"{root}/webservice/rest/server.php"
        function = {
            "assign": "mod_assign_get_assignments",
            "quiz": "mod_quiz_get_quizzes_by_courses",
        }[kind]
        parameters: dict[str, str] = {
            "moodlewsrestformat": "json",
            "moodlewssettingfileurl": "1",
            "moodlewssettingfilter": "1",
            "wsfunction": function,
            "wstoken": webservice_token,
            "courseids[0]": str(course_id),
        }
        payload, final_url, content_type = self._open(
            Request(
                f"{MOODLE_ORIGIN}{path}",
                data=urlencode(parameters).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
        )
        _require_json_endpoint(final_url, content_type, path)
        return _parse_activity_module_bulk(payload, root=root, kind=kind)

    def fetch_assignment_submissions_bulk(
        self,
        *,
        webservice_token: str,
        term: str,
        assignment_ids: list[int],
    ) -> dict[str, object]:
        """Read current-student assignment states through Moodle's student API.

        ``mod_assign_get_submissions`` is a bulk endpoint, but it is a grader
        endpoint in Moodle and therefore returns a permission error for a
        normal student account.  ``mod_assign_get_submission_status`` is the
        official student-facing endpoint.  Moodle accepts one assignment id
        per call, so we issue those bounded calls concurrently and keep the
        result shape compatible with the former bulk helper.  Failed individual
        calls are exposed in an internal metadata key; successful assignments
        can still skip HTML while only failed ones use the existing fallback.
        """

        _validate_mobile_service_token(webservice_token)
        if not assignment_ids or len(assignment_ids) > 500:
            raise InvalidMoodleResponse("assignment_submission_ids")
        if any(
            type(value) is not int or not 1 <= value <= 2_147_483_647
            for value in assignment_ids
        ):
            raise InvalidMoodleResponse("assignment_submission_id")
        root = _moodle_root(term)
        path = f"{root}/webservice/rest/server.php"
        unique_ids = sorted(set(assignment_ids))

        def fetch_one(assignment_id: int) -> tuple[str, dict[str, str | bool]]:
            parameters: dict[str, str] = {
                "moodlewsrestformat": "json",
                "moodlewssettingfileurl": "1",
                "moodlewssettingfilter": "1",
                "wsfunction": "mod_assign_get_submission_status",
                "wstoken": webservice_token,
                "assignid": str(assignment_id),
            }
            payload, final_url, content_type = self._open(
                Request(
                    f"{MOODLE_ORIGIN}{path}",
                    data=urlencode(parameters).encode(),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    method="POST",
                )
            )
            _require_json_endpoint(final_url, content_type, path)
            detail = timed_stage(
                "moodle_assignment_submission_status_parse",
                lambda: _parse_assignment_submission_status(payload),
                telemetry=self._telemetry,
                fields={
                    "term": term,
                    "assignment_id": assignment_id,
                    "response_bytes": len(payload),
                    "consumer": "activity_snapshot_submission_state",
                },
            )
            return str(assignment_id), detail

        statuses: dict[str, object] = {}
        failed_ids: list[int] = []
        worker_count = min(8, len(unique_ids))
        with ThreadPoolExecutor(
            max_workers=worker_count, thread_name_prefix="moodle-submission-status"
        ) as pool:
            futures = [pool.submit(fetch_one, assignment_id) for assignment_id in unique_ids]
            for assignment_id, future in zip(unique_ids, futures, strict=True):
                try:
                    key, detail = future.result()
                except Exception as error:
                    failed_ids.append(assignment_id)
                    _emit(
                        self._telemetry,
                        "moodle_assignment_submission_status_unavailable",
                        {
                            "term": term,
                            "assignment_id": assignment_id,
                            "reason": type(error).__name__,
                            "upstream_class": (
                                "moodle_response"
                                if isinstance(error, InvalidMoodleResponse)
                                else type(error).__name__.lower()
                            ),
                            "consumer": "activity_snapshot_submission_state",
                        },
                    )
                else:
                    statuses[key] = detail
        statuses["_bulk_failed_assignment_ids"] = failed_ids
        _emit(
            self._telemetry,
            "moodle_assignment_submission_status_bulk_completed",
            {
                "term": term,
                "assignment_count": len(unique_ids),
                "completed_count": len(unique_ids) - len(failed_ids),
                "failed_count": len(failed_ids),
                "consumer": "activity_snapshot_submission_state",
            },
        )
        return statuses

    def fetch_activity(
        self, token: str, *, term: str, source_id: int, kind: str
    ) -> dict[str, object]:
        if (
            type(source_id) is not int
            or not 1 <= source_id <= 2_147_483_647
            or kind not in {"assign", "quiz"}
        ):
            raise InvalidMoodleResponse("activity_source_id")
        _validate_token(token)
        digest = _token_digest(token)
        page_key = (digest, term, source_id, kind)
        with self._discovery_lock:
            cached_page = self._activity_page_cache.get(page_key)
        if cached_page is not None:
            # The same activity can be indexed by both the canonical course and a
            # metaturma; one bounded HTML page per (term, source_id, kind) is enough.
            _emit(
                self._telemetry,
                "moodle_activity_page_cache",
                {"term": term, "source_id": source_id, "kind": kind, "outcome": "hit"},
            )
            return dict(cached_page)
        root, _, _ = self._connect(token, term)
        path = f"{root}/mod/{kind}/view.php"
        payload, final_url, content_type = self._open(
            Request(f"{MOODLE_ORIGIN}{path}?id={source_id}", headers={"Accept": "text/html"})
        )
        parsed = urlsplit(final_url)
        if parsed.hostname == "sistemas.ufmg.br" or "/login/" in parsed.path:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "virtual.ufmg.br"
            or parsed.path != path
            or parse_qs(parsed.query).get("id") != [str(source_id)]
            or content_type != "text/html"
        ):
            raise InvalidMoodleResponse("activity_page_endpoint")
        try:
            detail = parse_activity_page(payload, term=term, kind=kind)
        except InvalidActivityPage as error:
            raise InvalidMoodleResponse(
                error.reason,
                details={"response_status": 200, "response_bytes": len(payload)},
            ) from None
        # Keep response-quality evidence with the in-memory detail only.  The
        # snapshot service strips these private fields before persistence, but
        # can use them to distinguish a valid page with no optional content
        # from a failed or incomplete HTML fallback.
        description = detail.get("description")
        attachments = detail.get("attachments")
        description_chars = len(description.strip()) if isinstance(description, str) else 0
        attachment_count = len(attachments) if isinstance(attachments, list) else 0
        empty_fields = []
        if description_chars == 0:
            empty_fields.append("description")
        if attachment_count == 0:
            empty_fields.append("attachments")
        detail = {
            **detail,
            "_html_response_status": 200,
            "_html_response_bytes": len(payload),
            "_html_description_chars": description_chars,
            "_html_attachment_count": attachment_count,
            "_html_empty_fields": empty_fields,
        }
        with self._discovery_lock:
            if len(self._activity_page_cache) < MAX_ACTIVITY_PAGE_CACHE:
                # Store a copy: the caller owns the returned dict and may mutate it.
                self._activity_page_cache[page_key] = dict(detail)
        _emit(
            self._telemetry,
            "moodle_activity_page_cache",
            {"term": term, "source_id": source_id, "kind": kind, "outcome": "miss"},
        )
        return detail

    def authorize_mobile_download(
        self,
        token: str,
        *,
        term: str,
    ) -> MoodleMobileAuthorization:
        """Obtain narrow file credentials for encrypted server-side persistence."""

        root, _, _ = self._connect(token, term)
        passport = token_hex(16)
        callback = self._mobile_launch(root, passport)
        webservice_token, callback_private_token = _mobile_tokens(callback, root, passport)
        info = self._site_info(root, webservice_token)
        download_files = info.get("downloadfiles") == 1
        site_private_token = info.get("userprivateaccesskey")
        valid_site_private_token = (
            site_private_token
            if isinstance(site_private_token, str) and _MOBILE_TOKEN.fullmatch(site_private_token)
            else None
        )
        private_token = callback_private_token or valid_site_private_token
        private_file_access = private_token is not None
        return MoodleMobileAuthorization(
            webservice_token=webservice_token,
            private_token=private_token,
            direct_download_supported=download_files and private_file_access,
            download_files=download_files,
            private_file_access=private_file_access,
        )

    def list_module_files(
        self,
        *,
        webservice_token: str,
        private_token: str,
        term: str,
        course_id: int,
        source_id: int,
    ) -> list[dict[str, object]]:
        """Resolve one enrolled file module to private-token download URLs."""

        _validate_mobile_file_request(
            webservice_token,
            private_token,
            course_id,
            source_id,
        )
        root = _moodle_root(term)
        path = f"{root}/webservice/rest/server.php"
        payload, final_url, content_type = self._open(
            Request(
                f"{MOODLE_ORIGIN}{path}",
                data=urlencode(
                    {
                        "moodlewsrestformat": "json",
                        "moodlewssettingfileurl": "1",
                        "moodlewssettingfilter": "1",
                        "wsfunction": "core_course_get_contents",
                        "wstoken": webservice_token,
                        "courseid": str(course_id),
                        "options[0][name]": "cmid",
                        "options[0][value]": str(source_id),
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
        )
        _require_json_endpoint(final_url, content_type, path)
        return timed_stage(
            "moodle_activity_module_bulk_parse",
            lambda: _parse_module_files(
                payload,
                root=root,
                source_id=source_id,
                private_token=private_token,
            ),
            telemetry=self._telemetry,
            fields={
                "term": term,
                "moodle_course_id": course_id,
                "kind": "module",
                "response_bytes": len(payload),
                "consumer": "activity_snapshot_attachments",
            },
        )

    def probe_diario_plan(
        self,
        token: str,
        *,
        term: str,
        source_id: int,
    ) -> DiarioPlanProbe:
        """Validate one Moodle plan link without retaining or returning its document."""

        delivery, body, document_format = self._fetch_diario_document(
            token, term=term, source_id=source_id
        )
        return DiarioPlanProbe(
            delivery=delivery,
            content_length=len(body),
            format=document_format,
        )

    def fetch_diario_plan(self, token: str, *, term: str, source_id: int) -> dict[str, object]:
        """Fetch and structure one official HTML teaching plan in memory."""

        _, body, document_format = self._fetch_diario_document(
            token, term=term, source_id=source_id
        )
        if document_format != "html":
            raise InvalidMoodleResponse("diario_plan_pdf_unstructured")
        try:
            result = timed_stage(
                "teaching_plan_parse",
                lambda: parse_teaching_plan_html(
                    _decode_diario_html(body, reason="diario_response_encoding")
                ),
                telemetry=self._telemetry,
                fields={
                    "term": term,
                    "source_id": source_id,
                    "response_bytes": len(body),
                    "consumer": "teaching_plan_and_assessment_dates",
                },
            )
        except TeachingPlanParseError as error:
            raise InvalidMoodleResponse(
                "diario_plan_structure", details=error.diagnostics
            ) from None
        if result["term"] != term:
            raise InvalidMoodleResponse("diario_plan_term")
        return result

    def _fetch_diario_document(
        self, token: str, *, term: str, source_id: int
    ) -> tuple[str, bytes, str]:
        if type(source_id) is not int or not 1 <= source_id <= 2_147_483_647:
            raise ValueError("invalid Diario source")
        root, _, _ = self._connect(token, term)
        launch_path = f"{root}/mod/url/view.php"
        body, final_url, content_type = self._open_bounded(
            Request(
                f"{MOODLE_ORIGIN}{launch_path}?{urlencode({'id': source_id})}",
                headers={"Accept": "text/html,application/pdf"},
            ),
            limit=MAX_DIARIO_BYTES,
        )
        delivery = "redirect"
        if _is_moodle_module(final_url, launch_path):
            form = _DiarioFormParser()
            try:
                form.feed(body.decode("utf-8"))
            except UnicodeDecodeError:
                raise InvalidMoodleResponse("diario_launch_encoding") from None
            action, fields = form.result()
            if fields is None:
                request = Request(
                    action,
                    headers={
                        "Accept": "text/html,application/pdf",
                        "Referer": f"{MOODLE_ORIGIN}{launch_path}",
                    },
                )
                delivery = "link"
            else:
                request = Request(
                    action,
                    data=urlencode(fields).encode(),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/html,application/pdf",
                        "Origin": MOODLE_ORIGIN,
                        "Referer": f"{MOODLE_ORIGIN}{launch_path}",
                    },
                    method="POST",
                )
                delivery = "form"
            body, final_url, content_type = self._open_bounded(
                request,
                limit=MAX_DIARIO_BYTES,
            )
            if _is_diario_request_url(final_url) and content_type == "text/html":
                transition_target = _diario_transition_target(body, final_url)
                body, final_url, content_type = self._open_bounded(
                    Request(
                        transition_target,
                        headers={
                            "Accept": "text/html,application/pdf",
                            "Referer": final_url,
                        },
                    ),
                    limit=MAX_DIARIO_BYTES,
                )
        document_format = _require_diario_document(final_url, content_type, body)
        return delivery, body, document_format

    def _mobile_launch(self, root: str, passport: str) -> str:
        launch_url = f"{MOODLE_ORIGIN}{root}/admin/tool/mobile/launch.php?" + urlencode(
            {
                "service": "moodle_mobile_app",
                "passport": passport,
                "urlscheme": "moodlemobile",
            }
        )
        request = Request(launch_url, headers={"Accept": "text/html"})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                response.read(MAX_RESPONSE_BYTES + 1)
                callback = response.geturl()
        except HTTPError as error:
            callback = error.headers.get("Location", "") if error.code in _REDIRECT_CODES else ""
            if not callback:
                raise MoodleUnavailable("Moodle is unavailable") from None
        except OSError:
            raise MoodleUnavailable("Moodle is unavailable") from None
        return callback

    def _site_info(self, root: str, webservice_token: str) -> dict[str, object]:
        path = f"{root}/webservice/rest/server.php"
        payload, final_url, content_type = self._open(
            Request(
                f"{MOODLE_ORIGIN}{path}",
                data=urlencode(
                    {
                        "moodlewsrestformat": "json",
                        "moodlewssettingfileurl": "1",
                        "moodlewssettingfilter": "1",
                        "wsfunction": "core_webservice_get_site_info",
                        "wstoken": webservice_token,
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                method="POST",
            )
        )
        _require_json_endpoint(final_url, content_type, path)
        try:
            info = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise InvalidMoodleResponse("site_info_json") from None
        if not isinstance(info, dict) or "exception" in info:
            raise InvalidMoodleResponse("site_info_rejected")
        return info

    def _connect(self, token: str, term: str) -> tuple[str, str, str]:
        _validate_token(token)
        token_digest = _token_digest(token)
        # Double-checked locking: concurrent callers share ONE SAML connection per
        # token/term, so the cookie jar and connection cache stay consistent.
        if token_digest == self._connection_token_digest:
            cached = self._connections.get(term)
            if cached is not None:
                _emit(
                    self._telemetry,
                    "moodle_session_connection_reused",
                    {"term": term, "outcome": "reused", "connection_count": self._connection_count},
                )
                return cached
        with self._connection_lock:
            if token_digest != self._connection_token_digest:
                self._connections.clear()
                # A new session token invalidates every per-sync memo: keys are
                # derived from the token digest, so they cannot be reused.
                self._clear_discovery_caches()
                self._connection_token_digest = token_digest
            cached = self._connections.get(term)
            if cached is not None:
                _emit(
                    self._telemetry,
                    "moodle_session_connection_reused",
                    {"term": term, "outcome": "reused", "connection_count": self._connection_count},
                )
                return cached
            root = _moodle_root(term)
            sso_url = f"{MOODLE_ORIGIN}{root}/auth/shibboleth/index.php"
            ajax_path = f"{root}/lib/ajax/service.php"
            if self._jar is not None:
                self._jar.clear(".sistemas.ufmg.br", "/", "LtpaToken2")
                self._jar.set_cookie(_ltpa_cookie(token))

            saml_page, saml_url, _ = self._open(Request(sso_url, headers={"Accept": "text/html"}))
            _require_identity_provider(saml_url)
            form = _SAMLFormParser()
            try:
                form.feed(saml_page.decode("utf-8"))
            except UnicodeDecodeError:
                raise InvalidMoodleResponse("sso_encoding") from None
            action, relay_state, assertion = form.result()
            _require_moodle_acs(action, root)

            dashboard, dashboard_url, _ = self._open(
                Request(
                    action,
                    data=urlencode({"RelayState": relay_state, "SAMLResponse": assertion}).encode(),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/html",
                    },
                    method="POST",
                )
            )
            _require_moodle_page(dashboard_url, root)
            match = _SESSKEY.search(dashboard)
            if match is None:
                raise UFMGReauthenticationRequired("UFMG reauthentication required")
            connection = (root, ajax_path, match.group(1).decode())
            self._connections[term] = connection
            self._connection_count += 1
            _emit(
                self._telemetry,
                "moodle_session_connection_created",
                {"term": term, "outcome": "created", "connection_count": self._connection_count},
            )
            return connection

    def _ajax(
        self,
        root: str,
        ajax_path: str,
        sesskey: str,
        calls: list[dict[str, object]],
    ) -> bytes:
        ajax_url = f"{MOODLE_ORIGIN}{ajax_path}?" + urlencode(
            {
                "sesskey": sesskey,
                "info": ",".join(str(call["methodname"]) for call in calls),
            }
        )
        payload, final_url, content_type = self._open(
            Request(
                ajax_url,
                data=json.dumps(calls, separators=(",", ":")).encode(),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
        )
        _require_ajax(final_url, content_type, ajax_path)
        _emit(
            self._telemetry,
            "moodle_ajax_batch_completed",
            {
                "term_path": root,
                "call_count": len(calls),
                "method_names": sorted({str(call.get("methodname", "unknown")) for call in calls}),
                "request_bytes": len(json.dumps(calls, separators=(",", ":")).encode()),
                "response_bytes": len(payload),
                "consumer": "moodle_sync",
            },
        )
        return payload

    def _open(self, request: Request) -> tuple[bytes, str, str]:
        return self._open_bounded(request, limit=MAX_RESPONSE_BYTES)

    def _next_request_sequence(self) -> int:
        """Return a unique call number for this client, including threaded calls."""

        with self._request_lock:
            self._request_sequence += 1
            return self._request_sequence

    def _open_bounded(self, request: Request, *, limit: int) -> tuple[bytes, str, str]:
        started = perf_counter()
        status: int | None = None
        response_body = b""
        outcome = "failed"
        reason: str | None = None
        response_content_type: str | None = None
        request_url = request.full_url
        request_sequence = self._next_request_sequence()
        try:
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    status = getattr(response, "status", None) or getattr(response, "code", None)
                    body = response.read(limit + 1)
                    response_body = body
                    url = response.geturl()
                    content_type = response.headers.get_content_type()
                    response_content_type = content_type
            except HTTPError as error:
                # HTTPError is an OSError subclass: classify it before the generic branch.
                status = error.code
                reason = "http_error"
                outcome = "upstream_error"
                raise MoodleUnavailable(
                    "Moodle is unavailable", upstream_status=error.code
                ) from None
            except TimeoutError:
                reason = "timeout"
                outcome = "timeout"
                raise MoodleUnavailable("Moodle is unavailable", timed_out=True) from None
            except OSError as error:
                timed_out = isinstance(error, URLError) and isinstance(error.reason, TimeoutError)
                reason = "timeout" if timed_out else type(error).__name__
                outcome = "timeout" if timed_out else "network_error"
                raise MoodleUnavailable("Moodle is unavailable", timed_out=timed_out) from None
            if len(body) > limit:
                reason = "response_oversized"
                outcome = "response_oversized"
                raise InvalidMoodleResponse("response_oversized")
            outcome = "succeeded"
            return body, url, content_type
        finally:
            parsed = urlsplit(request_url)
            _emit(
                self._telemetry,
                "moodle_http_request_completed",
                {
                    "operation": _request_operation(request),
                    "host": parsed.hostname or "unknown",
                    "path": parsed.path or "/",
                    "method": request.get_method() or "GET",
                    "status_code": status,
                    "status_class": f"{status // 100}xx" if status is not None else "network",
                    "outcome": outcome,
                    "reason": reason or "",
                    "duration_ms": round((perf_counter() - started) * 1_000, 3),
                    "timeout_seconds": self._timeout,
                    "request_bytes": _request_size(request.data),
                    "response_bytes": len(response_body),
                    "response_content_type": response_content_type or "",
                    "request_sequence": request_sequence,
                    "retry_count": 0,
                    "attempt": 1,
                },
            )


def _request_size(data: object) -> int:
    return len(data) if isinstance(data, (bytes, bytearray)) else 0


def _request_operation(request: Request) -> str:
    """Identify an allowlisted Moodle operation without logging credentials."""

    parsed = urlsplit(request.full_url)
    if parsed.path.endswith("/lib/ajax/service.php"):
        query_values = parse_qs(parsed.query).get("info", [])
        methods = re.findall(r"[a-z][a-z0-9_]{2,80}", ",".join(query_values))
        return (
            "moodle_ajax:" + ",".join(sorted(set(methods)))
            if methods
            else "moodle_ajax:unknown"
        )
    if parsed.path.endswith("/webservice/rest/server.php"):
        request_data = request.data
        raw_data = request_data if isinstance(request_data, (bytes, bytearray)) else b""
        body_values = parse_qs(raw_data.decode("ascii", errors="ignore"))
        function = body_values.get("wsfunction", ["unknown"])[0]
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,100}", function):
            function = "unknown"
        return f"moodle_webservice:{function}"
    if parsed.path.endswith("/mod/url/view.php"):
        return "moodle_diario_launch"
    if re.search(r"/mod/(assign|quiz)/view\.php$", parsed.path):
        return "moodle_activity_page"
    if parsed.hostname == "sistemas.ufmg.br" and parsed.path == "/diario/JasperServlet":
        return "ufmg_diario_jasper"
    return "moodle_http"


class _SAMLFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.values: dict[str, str] = {}
        self._in_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        method = values.get("method")
        if tag == "form" and isinstance(method, str) and method.lower() == "post":
            self._in_form = True
            self.action = values.get("action")
        elif tag == "input" and self._in_form:
            name = values.get("name")
            value = values.get("value")
            if name in {"RelayState", "SAMLResponse"} and value is not None:
                self.values[name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._in_form = False

    def result(self) -> tuple[str, str, str]:
        action = self.action
        relay_state = self.values.get("RelayState")
        assertion = self.values.get("SAMLResponse")
        if (
            not action
            or not relay_state
            or len(relay_state) > 8_192
            or not assertion
            or len(assertion) > 512_000
        ):
            raise InvalidMoodleResponse("sso_form")
        return action, relay_state, assertion


class _DiarioFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._active = False
        self._action: str | None = None
        self._fields: dict[str, str] = {}
        self._get_targets: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            action = values.get("action")
            method = values.get("method", "get")
            if _is_diario_url(action) and isinstance(method, str) and method.lower() == "post":
                if self._action is not None:
                    raise InvalidMoodleResponse("diario_launch_forms")
                self._active = True
                self._action = action
        elif tag in {"a", "iframe", "embed", "object"}:
            attribute = "data" if tag == "object" else "href" if tag == "a" else "src"
            target = values.get(attribute)
            if isinstance(target, str) and _is_diario_launch_url(target):
                self._get_targets.add(target)
                if len(self._get_targets) > 1:
                    raise InvalidMoodleResponse("diario_launch_targets")
        elif tag == "input" and self._active:
            name = values.get("name")
            value = values.get("value", "")
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) is None
                or not isinstance(value, str)
                or len(value) > 4_096
                or name in self._fields
            ):
                raise InvalidMoodleResponse("diario_launch_field")
            self._fields[name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._active = False

    def result(self) -> tuple[str, dict[str, str] | None]:
        if self._action is not None:
            if not self._fields or len(self._fields) > 32:
                raise InvalidMoodleResponse("diario_launch_form")
            return self._action, self._fields
        if len(self._get_targets) == 1:
            return next(iter(self._get_targets)), None
        raise InvalidMoodleResponse("diario_launch_target")


def _parse_calendar(payload: bytes, expected_calls: int) -> list[dict[str, str]]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("calendar_json") from None
    if not isinstance(decoded, list):
        raise InvalidMoodleResponse("calendar_batch_type")
    if len(decoded) != expected_calls:
        raise InvalidMoodleResponse("calendar_call_count")
    events: dict[str, dict[str, str]] = {}
    try:
        for item in decoded:
            if not isinstance(item, dict):
                raise ValueError("calendar_call_shape")
            if item.get("error") is not False:
                raise ValueError("calendar_upstream_error")
            data = item.get("data")
            if not isinstance(data, dict):
                raise ValueError("calendar_call_data")
            for raw in _calendar_events(data):
                # Moodle legitimately omits `course` for site-wide and personal
                # calendar events. They cannot be matched to a local discipline
                # without guessing, so keep parsing the scoped course events.
                if raw.get("course") is None:
                    continue
                event = _event(raw)
                previous = events.get(event["source_id"])
                if previous is not None and previous != event:
                    raise ValueError("calendar_event_conflict")
                events[event["source_id"]] = event
                if len(events) > MAX_EVENTS:
                    raise ValueError("calendar_event_limit")
    except (KeyError, TypeError, ValueError) as error:
        reason = str(error) if error.args else "calendar_shape"
        raise InvalidMoodleResponse(reason) from None
    return sorted(events.values(), key=lambda item: (item["due_at"], item["source_id"]))


def _calendar_events(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    weeks = data.get("weeks")
    if not isinstance(weeks, list) or len(weeks) > 6:
        raise ValueError("calendar_weeks")
    for week in weeks:
        if not isinstance(week, dict):
            raise ValueError("calendar_week")
        days = week.get("days")
        if not isinstance(days, list) or len(days) > 7:
            raise ValueError("calendar_days")
        for day in days:
            if not isinstance(day, dict):
                raise ValueError("calendar_day")
            events = day.get("events", [])
            if not isinstance(events, list) or len(events) > 100:
                raise ValueError("calendar_events")
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("calendar_event_shape")
                yield event


def _event(raw: dict[str, Any]) -> dict[str, str]:
    event_id = raw.get("id")
    title = raw.get("name")
    timestamp = raw.get("timestart")
    course = raw.get("course")
    module = raw.get("modulename")
    if (
        type(event_id) is not int
        or event_id < 1
        or not isinstance(title, str)
        or title.strip() != title
        or not title
        or len(title) > 120
        or type(timestamp) is not int
        or timestamp < 946_684_800
        or timestamp > 4_102_444_800
        or not isinstance(course, dict)
    ):
        raise ValueError("calendar_event_fields")
    course_id = course.get("id")
    shortname = course.get("shortname")
    fullname = course.get("fullname")
    if (
        type(course_id) is not int
        or course_id < 1
        or not isinstance(shortname, str)
        or not _valid_text(shortname, 160)
        or not isinstance(fullname, str)
        or not _valid_text(fullname, 240)
    ):
        raise ValueError("calendar_course_fields")
    return {
        "source_id": str(event_id),
        "title": title,
        "due_at": datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z"),
        "moodle_course_id": str(course_id),
        "course_shortname": shortname,
        "course_fullname": fullname,
        "kind": {"assign": "assignment", "quiz": "quiz"}.get(
            module if isinstance(module, str) else "", "event"
        ),
    }


def _valid_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value and len(value) <= limit


def _validate_token(token: str) -> None:
    if not token or len(token) > 4_096 or any(character.isspace() for character in token):
        raise ValueError("invalid UFMG session")


def _validate_inputs(token: str, months: list[tuple[int, int]]) -> None:
    _validate_token(token)
    if (
        not months
        or len(months) > MAX_MONTHS
        or len(set(months)) != len(months)
        or any(
            type(year) is not int
            or type(month) is not int
            or year < 2020
            or year > 2100
            or month < 1
            or month > 12
            for year, month in months
        )
    ):
        raise ValueError("invalid Moodle month range")


def _validate_course_codes(token: str, course_codes: list[str]) -> list[str]:
    _validate_token(token)
    if (
        not course_codes
        or len(course_codes) > MAX_COURSES
        or len(set(course_codes)) != len(course_codes)
        or any(
            not isinstance(code, str)
            or not code
            or code != code.strip().upper()
            or len(code) > 32
            or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]*", code) is None
            for code in course_codes
        )
    ):
        raise ValueError("invalid Moodle course codes")
    return sorted(course_codes)


def _parse_course_list(payload: bytes) -> list[dict[str, object]]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("course_list_json") from None
    if not isinstance(decoded, list):
        raise InvalidMoodleResponse("course_list_batch_type")
    if len(decoded) != 1:
        raise InvalidMoodleResponse("course_list_call_count")
    try:
        item = decoded[0]
        if not isinstance(item, dict):
            raise ValueError("course_list_call_shape")
        if item.get("error") is not False:
            raise ValueError("course_list_upstream_error")
        data = item.get("data")
        if not isinstance(data, dict):
            raise ValueError("course_list_data")
        raw_courses = data.get("courses")
        next_offset = data.get("nextoffset")
        if (
            not isinstance(raw_courses, list)
            or len(raw_courses) > 100
            or type(next_offset) is not int
            or next_offset < 0
            or next_offset > 10_000
        ):
            raise ValueError("course_list_fields")
        courses: dict[int, dict[str, object]] = {}
        for raw in raw_courses:
            if not isinstance(raw, dict):
                raise ValueError("course_shape")
            course_id = raw.get("id")
            shortname = raw.get("shortname")
            fullname = raw.get("fullname")
            if (
                type(course_id) is not int
                or course_id < 1
                or not _valid_text(shortname, 160)
                or not _valid_text(fullname, 240)
            ):
                raise ValueError("course_fields")
            course = {"id": course_id, "shortname": shortname, "fullname": fullname}
            previous = courses.get(course_id)
            if previous is not None and previous != course:
                raise ValueError("course_conflict")
            courses[course_id] = course
    except (KeyError, TypeError, ValueError) as error:
        reason = str(error) if error.args else "course_list_shape"
        raise InvalidMoodleResponse(reason) from None
    return [courses[course_id] for course_id in sorted(courses)]


def _course_matches(code: str, course: dict[str, object]) -> bool:
    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", re.IGNORECASE)
    return any(
        pattern.search(str(course[field])) is not None for field in ("shortname", "fullname")
    )


def _is_metaturma(course: dict[str, object]) -> bool:
    pattern = re.compile(r"(?<![A-Z0-9])METATURMA(?![A-Z0-9])", re.IGNORECASE)
    return any(
        pattern.search(" ".join(str(course[field]).split())) is not None
        for field in ("shortname", "fullname")
    )


_MATERIAL_MODULE_KINDS: Final = {
    "page": "page",
    "book": "page",
    "resource": "file",
    "folder": "file",
    "label": "text",
    "url": "link",
}
_ACTIVITY_MODULE_KINDS: Final = {"assign": "assign", "quiz": "quiz"}


def _parse_course_states(
    payload: bytes,
    root: str,
    expected_calls: int,
    *,
    activities: bool = False,
) -> list[list[dict[str, object]]]:
    """Return one candidate list per course for the requested view only."""
    full = _parse_course_states_full(payload, root, expected_calls)
    return [state["activities" if activities else "materials"] for state in full]


def _parse_course_states_full(
    payload: bytes,
    root: str,
    expected_calls: int,
) -> list[dict[str, list[dict[str, object]]]]:
    """Parse one course-state batch into both material and activity views.

    One ``core_courseformat_get_state`` response is parsed once and cached per
    course, so the material catalog consumer and the activity index consumer
    share the same Moodle request inside a single sync run.
    """
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("course_state_json") from None
    if not isinstance(decoded, list):
        raise InvalidMoodleResponse("course_state_batch_type")
    if len(decoded) != expected_calls:
        raise InvalidMoodleResponse("course_state_call_count")
    states: list[dict[str, list[dict[str, object]]]] = []
    try:
        for item in decoded:
            if not isinstance(item, dict):
                raise ValueError("course_state_call_shape")
            if item.get("error") is not False:
                raise ValueError("course_state_upstream_error")
            raw_data = item.get("data")
            if not isinstance(raw_data, str) or len(raw_data) > MAX_RESPONSE_BYTES:
                raise ValueError("course_state_data")
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                raise ValueError("course_state_inner_json") from None
            if not isinstance(data, dict):
                raise ValueError("course_state_inner_shape")
            raw_modules = data.get("cm")
            if not isinstance(raw_modules, list) or len(raw_modules) > 500:
                raise ValueError("course_modules")
            materials: dict[str, dict[str, object]] = {}
            activity_modules: dict[str, dict[str, object]] = {}
            for raw in raw_modules:
                if not isinstance(raw, dict):
                    raise ValueError("course_module_shape")
                if raw.get("uservisible") is not True:
                    continue
                module = str(raw.get("module"))
                material_kind = _MATERIAL_MODULE_KINDS.get(module)
                activity_kind = _ACTIVITY_MODULE_KINDS.get(module)
                if material_kind is None and activity_kind is None:
                    continue
                raw_source_id = raw.get("id")
                raw_title = raw.get("name")
                if type(raw_source_id) is int:
                    source_id = raw_source_id
                elif isinstance(raw_source_id, str):
                    if re.fullmatch(r"[1-9][0-9]{0,9}", raw_source_id) is None:
                        raise ValueError("course_module_id_format")
                    source_id = int(raw_source_id)
                else:
                    raise ValueError("course_module_id_type")
                if source_id < 1 or source_id > 2_147_483_647:
                    raise ValueError("course_module_id_range")
                if not isinstance(raw_title, str):
                    raise ValueError("course_module_title_type")
                title = raw_title.strip()
                if not title:
                    raise ValueError("course_module_title_empty")
                if len(title) > 1_024:
                    raise ValueError("course_module_title_length")
                base: dict[str, object] = {
                    "source_id": str(source_id),
                    "title": title,
                    "url": None
                    if module == "label"
                    else _candidate_url(raw.get("url"), root, str(module), source_id),
                    "relevance": _candidate_relevance(title),
                }
                if material_kind is not None:
                    candidate = base | {"kind": material_kind}
                    previous = materials.get(str(source_id))
                    if previous is not None and previous != candidate:
                        raise ValueError("course_module_conflict")
                    materials[str(source_id)] = candidate
                if activity_kind is not None:
                    candidate = base | {"kind": activity_kind}
                    previous = activity_modules.get(str(source_id))
                    if previous is not None and previous != candidate:
                        raise ValueError("course_module_conflict")
                    activity_modules[str(source_id)] = candidate
            def sort_key(candidate: dict[str, object]) -> tuple[int, str]:
                return int(str(candidate["source_id"])), str(candidate["title"])

            states.append(
                {
                    "materials": sorted(materials.values(), key=sort_key),
                    "activities": sorted(activity_modules.values(), key=sort_key),
                }
            )
    except (KeyError, TypeError, ValueError) as error:
        reason = str(error) if error.args else "course_state_shape"
        raise InvalidMoodleResponse(reason) from None
    return states


def _parse_activity_updates(payload: bytes) -> set[int]:
    """Parse one ``core_course_get_updates_since`` AJAX response."""

    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, list) or len(decoded) != 1:
            raise ValueError("activity_updates_call_count")
        item = decoded[0]
        if not isinstance(item, dict) or item.get("error") is not False:
            raise ValueError("activity_updates_upstream_error")
        raw_data = item.get("data")
        if isinstance(raw_data, str):
            if len(raw_data) > MAX_RESPONSE_BYTES:
                raise ValueError("activity_updates_data")
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                raise ValueError("activity_updates_inner_json") from None
        if not isinstance(raw_data, dict):
            raise ValueError("activity_updates_data")
        if "instances" not in raw_data:
            raise ValueError("activity_updates_instances")
        raw_instances = raw_data["instances"]
        if not isinstance(raw_instances, list) or len(raw_instances) > 500:
            raise ValueError("activity_updates_instances")
        changed: set[int] = set()
        for raw_instance in raw_instances:
            if not isinstance(raw_instance, dict):
                raise ValueError("activity_updates_instance")
            raw_id = raw_instance.get("id")
            if type(raw_id) is not int or not 1 <= raw_id <= 2_147_483_647:
                raise ValueError("activity_updates_instance_id")
            updates = raw_instance.get("updates", [])
            if not isinstance(updates, list) or len(updates) > 100:
                raise ValueError("activity_updates_list")
            if updates:
                changed.add(raw_id)
        return changed
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        reason = (
            str(error)
            if error.args and re.fullmatch(r"[a-z_]{1,64}", str(error))
            else "activity_updates_shape"
        )
        raise InvalidMoodleResponse(reason) from None


def _parse_course_activity_contents(
    payload: bytes, *, root: str
) -> dict[str, dict[str, object]]:
    """Extract assignment/quiz details from Moodle's course-wide contents."""

    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, list) or len(decoded) > 100:
            raise ValueError("course_contents_shape")
        activities: dict[str, dict[str, object]] = {}
        for section in decoded:
            if not isinstance(section, dict):
                raise ValueError("course_section_shape")
            modules = section.get("modules", [])
            if not isinstance(modules, list) or len(modules) > 500:
                raise ValueError("course_contents_modules")
            for module in modules:
                if not isinstance(module, dict) or module.get("uservisible") is False:
                    continue
                kind = module.get("modname")
                if kind not in {"assign", "quiz"}:
                    continue
                source_id = module.get("id")
                title = module.get("name")
                if (
                    type(source_id) is not int
                    or not 1 <= source_id <= 2_147_483_647
                    or not isinstance(title, str)
                    or not title.strip()
                    or len(title) > 1_024
                ):
                    raise ValueError("course_activity_fields")
                dates = _course_activity_dates(module.get("dates", []))
                attachments = _course_activity_attachments(
                    module.get("contents", []), root=root
                )
                candidate: dict[str, object] = {
                    "description": plain_activity_text(module.get("description")),
                    # Moodle's course-wide export may omit fields that the
                    # activity page still exposes.  Keep these provenance
                    # flags internal so the caller can decide when to use the
                    # precise HTML fallback without persisting them in the
                    # user-facing snapshot.
                    "_bulk_description_present": "description" in module,
                    "_bulk_attachments_present": "contents" in module,
                    "dates_text": dates["text"],
                    "has_due_date": dates["has_due_date"],
                    "submission_state": "unknown",
                    "submission_text": "",
                    # The course-wide service has no student-specific
                    # submission status.  The snapshot stage enriches this
                    # with Moodle's student-facing status endpoint before it
                    # decides whether an HTML fallback is necessary.
                    "_bulk_submission_complete": False,
                    "attachments": attachments,
                }
                identifier = str(source_id)
                previous = activities.get(identifier)
                if previous is not None and previous != candidate:
                    raise ValueError("course_activity_conflict")
                activities[identifier] = candidate
        return activities
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        reason = (
            str(error)
            if error.args and re.fullmatch(r"[a-z_]{1,64}", str(error))
            else "course_contents_shape"
        )
        raise InvalidMoodleResponse(reason) from None


def _parse_assignment_submission_status(payload: bytes) -> dict[str, str | bool]:
    """Normalize one student-facing ``mod_assign_get_submission_status`` reply."""

    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or "exception" in decoded:
            raise ValueError("assignment_submission_status_upstream_error")
        last_attempt = decoded.get("lastattempt")
        if last_attempt is None:
            state, text = "not_submitted", "Nenhum envio"
        else:
            if not isinstance(last_attempt, dict):
                raise ValueError("assignment_submission_status_last_attempt")
            submission = last_attempt.get("submission")
            if submission is None:
                state, text = "not_submitted", "Nenhum envio"
            else:
                if not isinstance(submission, dict):
                    raise ValueError("assignment_submission_status_submission")
                raw_status = submission.get("status", "")
                if not isinstance(raw_status, str) or len(raw_status) > 200:
                    raise ValueError("assignment_submission_status_value")
                text = raw_status.strip()
                normalized = text.lower()
                if not normalized or normalized == "new":
                    state, text = "not_submitted", "Nenhum envio"
                elif normalized == "draft":
                    state = "draft"
                elif normalized in {"submitted", "graded", "reopened", "returned"}:
                    state = "submitted"
                else:
                    state = "unknown"
        return {
            "submission_state": state,
            "submission_text": text[:200],
            "_bulk_submission_complete": True,
        }
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        reason = (
            str(error)
            if error.args and re.fullmatch(r"[a-z_]{1,64}", str(error))
            else "assignment_submission_status_shape"
        )
        raise InvalidMoodleResponse(reason) from None


def _parse_assignment_submissions_bulk(payload: bytes) -> dict[str, dict[str, str | bool]]:
    """Normalize ``mod_assign_get_submissions`` for the current student."""

    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or "exception" in decoded:
            raise ValueError("assignment_submission_upstream_error")
        raw_assignments = decoded.get("assignments")
        if not isinstance(raw_assignments, list) or len(raw_assignments) > 500:
            raise ValueError("assignment_submission_assignments")
        result: dict[str, dict[str, str | bool]] = {}
        for raw_assignment in raw_assignments:
            if not isinstance(raw_assignment, dict):
                raise ValueError("assignment_submission_assignment")
            assignment_id = raw_assignment.get("assignmentid", raw_assignment.get("id"))
            if (
                type(assignment_id) is not int
                or not 1 <= assignment_id <= 2_147_483_647
            ):
                raise ValueError("assignment_submission_id")
            submissions = raw_assignment.get("submissions", [])
            if not isinstance(submissions, list) or len(submissions) > 100:
                raise ValueError("assignment_submission_items")
            status = ""
            if submissions:
                current = submissions[0]
                if not isinstance(current, dict):
                    raise ValueError("assignment_submission_item")
                raw_status = current.get("status", "")
                if not isinstance(raw_status, str) or len(raw_status) > 200:
                    raise ValueError("assignment_submission_status")
                status = raw_status.strip()
            normalized = status.lower()
            if not submissions or normalized in {"new", "not_submitted"}:
                state, text = "not_submitted", "Nenhum envio"
            elif normalized == "draft":
                state, text = "draft", status
            elif normalized in {"submitted", "graded", "reopened", "returned"}:
                state, text = "submitted", status
            else:
                state, text = "unknown", status
            item: dict[str, str | bool] = {
                "submission_state": state,
                "submission_text": text[:200],
                "_bulk_submission_complete": True,
            }
            previous = result.get(str(assignment_id))
            if previous is not None and previous != item:
                raise ValueError("assignment_submission_conflict")
            result[str(assignment_id)] = item
        return result
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        reason = (
            str(error)
            if error.args and re.fullmatch(r"[a-z_]{1,64}", str(error))
            else "assignment_submission_shape"
        )
        raise InvalidMoodleResponse(reason) from None


def _parse_activity_module_bulk(
    payload: bytes, *, root: str, kind: str
) -> dict[str, dict[str, object]]:
    """Normalize Moodle's assignment/quiz bulk response to snapshot details."""

    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or "exception" in decoded:
            raise ValueError("activity_module_upstream_error")
        if kind == "assign":
            raw_courses = decoded.get("courses")
            item_key = "assignments"
        else:
            raw_courses = [{"quizzes": decoded.get("quizzes")}]
            item_key = "quizzes"
        if not isinstance(raw_courses, list) or len(raw_courses) > 100:
            raise ValueError("activity_module_courses")
        activities: dict[str, dict[str, object]] = {}
        for course in raw_courses:
            if not isinstance(course, dict):
                raise ValueError("activity_module_course")
            raw_items = course.get(item_key, [])
            if not isinstance(raw_items, list) or len(raw_items) > 500:
                raise ValueError("activity_module_items")
            for raw in raw_items:
                if not isinstance(raw, dict):
                    raise ValueError("activity_module_item")
                source_id = raw.get("cmid" if kind == "assign" else "coursemodule")
                if type(source_id) is not int or not 1 <= source_id <= 2_147_483_647:
                    raise ValueError("activity_module_id")
                title = raw.get("name")
                if not isinstance(title, str) or not title.strip() or len(title) > 1_024:
                    raise ValueError("activity_module_title")
                assignment_id = raw.get("id") if kind == "assign" else None
                if assignment_id is not None and (
                    type(assignment_id) is not int
                    or not 1 <= assignment_id <= 2_147_483_647
                ):
                    raise ValueError("activity_module_assignment_id")
                attachments = _module_activity_attachments(raw, root=root)
                dates = _module_activity_dates(raw, kind=kind)
                candidate: dict[str, object] = {
                    "description": _module_activity_description(raw, kind=kind),
                    "_bulk_description_present": _module_description_present(raw, kind=kind),
                    "_bulk_attachments_present": _module_attachments_present(raw, kind=kind),
                    "dates_text": dates["text"],
                    "has_due_date": dates["has_due_date"],
                    "submission_state": "unknown",
                    "submission_text": "",
                    "_bulk_submission_complete": False,
                    "attachments": attachments,
                }
                if assignment_id is not None:
                    candidate["_bulk_assignment_id"] = assignment_id
                identifier = str(source_id)
                previous = activities.get(identifier)
                if previous is not None and previous != candidate:
                    raise ValueError("activity_module_conflict")
                activities[identifier] = candidate
        return activities
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        reason = (
            str(error)
            if error.args and re.fullmatch(r"[a-z_]{1,64}", str(error))
            else "activity_module_shape"
        )
        raise InvalidMoodleResponse(reason) from None


def _module_activity_description(raw: dict[str, object], *, kind: str) -> str:
    """Keep both the assignment statement and its submission instructions."""

    keys = ("intro", "activity") if kind == "assign" else ("intro",)
    parts = [plain_activity_text(raw.get(key)) for key in keys]
    return "\n\n".join(part for part in parts if part)[:20_000]


def _module_description_present(raw: dict[str, object], *, kind: str) -> bool:
    keys = ("intro", "activity") if kind == "assign" else ("intro",)
    return all(key in raw for key in keys)


def _module_attachments_present(raw: dict[str, object], *, kind: str) -> bool:
    if kind == "assign":
        return "introattachments" in raw and "activityattachments" in raw
    # The quiz mobile endpoint does not consistently expose file lists.  Keep
    # the HTML fallback when the installation omits them rather than silently
    # losing offline attachments.
    return "introattachments" in raw or "contents" in raw


def _module_activity_attachments(
    raw: dict[str, object], *, root: str
) -> list[dict[str, str]]:
    values: list[object] = []
    for key in ("introattachments", "activityattachments", "contents"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("activity_module_attachments")
        values.extend(value)
    attachments: dict[str, dict[str, str]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("activity_module_attachment")
        if value.get("type", "file") != "file":
            continue
        name = value.get("filename")
        if not isinstance(name, str) or not name or name.strip() != name or len(name) > 255:
            raise ValueError("activity_module_attachment_name")
        url = _canonical_file_url(value.get("fileurl"), root)
        item = {"name": name, "url": url}
        previous = attachments.get(url)
        if previous is not None and previous != item:
            raise ValueError("activity_module_attachment_conflict")
        attachments[url] = item
    return sorted(attachments.values(), key=lambda item: (item["name"], item["url"]))


def _module_activity_dates(raw: dict[str, object], *, kind: str) -> dict[str, object]:
    fields = (
        (("allowsubmissionsfromdate", "Disponível a partir de"),
         ("duedate", "Vencimento"),
         ("cutoffdate", "Prazo final"),
         ("gradingduedate", "Correção até"))
        if kind == "assign"
        else (("timeopen", "Disponível a partir de"), ("timeclose", "Encerramento"))
    )
    parts: list[str] = []
    has_due_date = False
    for key, label in fields:
        value = raw.get(key, 0)
        if type(value) is not int or value < 0 or value > 4_102_444_800:
            raise ValueError("activity_module_date")
        if value == 0:
            continue
        has_due_date |= key in {"duedate", "cutoffdate", "timeclose"}
        parts.append(f"{label}: {datetime.fromtimestamp(value, UTC).isoformat()}")
    return {"text": " ".join(parts)[:2_000], "has_due_date": has_due_date}


def _course_activity_dates(value: object) -> dict[str, object]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("course_activity_dates")
    parts: list[str] = []
    has_due_date = False
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("course_activity_date")
        label = item.get("label")
        timestamp = item.get("timestamp")
        if not isinstance(label, str) or len(label) > 200 or type(timestamp) is not int:
            raise ValueError("course_activity_date_fields")
        if timestamp < 0 or timestamp > 4_102_444_800:
            raise ValueError("course_activity_date_range")
        normalized = "".join(
            char
            for char in unicodedata.normalize("NFKD", label).lower()
            if not unicodedata.combining(char)
        )
        has_due_date |= normalized.startswith(("vencimento", "due date", "due"))
        parts.append(f"{label}: {datetime.fromtimestamp(timestamp, UTC).isoformat()}")
    return {"text": " ".join(parts)[:2_000], "has_due_date": has_due_date}


def _course_activity_attachments(value: object, *, root: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError("course_activity_contents")
    attachments: dict[str, dict[str, str]] = {}
    for item in value:
        if not isinstance(item, dict) or item.get("type", "file") != "file":
            continue
        name = item.get("filename")
        if not isinstance(name, str) or not name or name.strip() != name or len(name) > 255:
            raise ValueError("course_activity_attachment_name")
        # Snapshots must never persist a private token.  The token is added only
        # by authorize_saved immediately before a user opens a downloaded file.
        url = _canonical_file_url(item.get("fileurl"), root)
        attachment = {"name": name, "url": url}
        previous = attachments.get(url)
        if previous is not None and previous != attachment:
            raise ValueError("course_activity_attachment_conflict")
        attachments[url] = attachment
    return sorted(attachments.values(), key=lambda item: (item["name"], item["url"]))


def _parse_module_files(
    payload: bytes,
    *,
    root: str,
    source_id: int,
    private_token: str,
) -> list[dict[str, object]]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("module_files_json") from None
    if isinstance(decoded, dict) and "exception" in decoded:
        raise InvalidMoodleResponse("module_files_rejected")
    if not isinstance(decoded, list) or len(decoded) > 100:
        raise InvalidMoodleResponse("module_files_shape")
    matching: list[dict[str, object]] = []
    try:
        for section in decoded:
            if not isinstance(section, dict):
                raise ValueError("module_section_shape")
            modules = section.get("modules", [])
            if not isinstance(modules, list) or len(modules) > 500:
                raise ValueError("module_list_shape")
            matching.extend(
                module
                for module in modules
                if isinstance(module, dict) and module.get("id") == source_id
            )
        if len(matching) != 1:
            raise ValueError("module_not_found" if not matching else "module_conflict")
        module = matching[0]
        if module.get("modname") not in {"resource", "folder"}:
            raise ValueError("module_kind")
        contents = module.get("contents", [])
        if not isinstance(contents, list) or len(contents) > 100:
            raise ValueError("module_contents_shape")
        files: dict[str, dict[str, object]] = {}
        for raw in contents:
            if not isinstance(raw, dict):
                raise ValueError("module_file_shape")
            if raw.get("type", "file") != "file":
                continue
            name = raw.get("filename")
            size = raw.get("filesize", 0)
            mime_type = raw.get("mimetype", "application/octet-stream")
            if (
                not isinstance(name, str)
                or not name
                or name.strip() != name
                or len(name) > 255
                or type(size) is not int
                or size < 0
                or size > 10_000_000_000
                or not isinstance(mime_type, str)
                or not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime_type)
            ):
                raise ValueError("module_file_fields")
            url = _private_file_url(raw.get("fileurl"), root, private_token)
            item = {"name": name, "url": url, "size": size, "mime_type": mime_type}
            previous = files.get(url)
            if previous is not None and previous != item:
                raise ValueError("module_file_conflict")
            files[url] = item
        return sorted(files.values(), key=lambda item: (str(item["name"]), str(item["url"])))
    except (TypeError, ValueError) as error:
        reason = str(error) if error.args else "module_files_shape"
        raise InvalidMoodleResponse(reason) from None


def _private_file_url(value: object, root: str, private_token: str) -> str:
    if not isinstance(value, str) or len(value) > 4_096:
        raise ValueError("module_file_url")
    parsed = urlsplit(value)
    prefixes = (
        f"{root}/webservice/pluginfile.php/",
        f"{root}/pluginfile.php/",
    )
    prefix = next((candidate for candidate in prefixes if parsed.path.startswith(candidate)), None)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "virtual.ufmg.br"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or prefix is None
    ):
        raise ValueError("module_file_url")
    suffix = parsed.path.removeprefix(prefix)
    segments = suffix.split("/")
    if (
        len(segments) < 5
        or any(not segment or segment in {".", ".."} for segment in segments)
        or any("\\" in segment for segment in segments)
    ):
        raise ValueError("module_file_url")
    return f"{MOODLE_ORIGIN}{root}/tokenpluginfile.php/{private_token}/{suffix}?forcedownload=1"


def _canonical_file_url(value: object, root: str) -> str:
    """Return a token-free canonical pluginfile URL for snapshot storage."""

    if not isinstance(value, str) or len(value) > 4_096:
        raise ValueError("module_file_url")
    parsed = urlsplit(value)
    prefixes = (
        f"{root}/webservice/pluginfile.php/",
        f"{root}/pluginfile.php/",
        f"{root}/tokenpluginfile.php/",
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "virtual.ufmg.br"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("module_file_url")
    prefix = next((candidate for candidate in prefixes if parsed.path.startswith(candidate)), None)
    if prefix is None:
        raise ValueError("module_file_url")
    suffix = parsed.path.removeprefix(prefix)
    segments = suffix.split("/")
    # tokenpluginfile paths contain the private token between the endpoint and
    # the actual file path; remove it before persisting the canonical URL.
    if prefix.endswith("tokenpluginfile.php/"):
        if len(segments) < 2 or not segments[0] or _MOBILE_TOKEN.fullmatch(segments[0]) is None:
            raise ValueError("module_file_url")
        suffix = "/".join(segments[1:])
        segments = suffix.split("/")
    if (
        len(segments) < 5
        or any(not segment or segment in {".", ".."} for segment in segments)
        or any("\\" in segment for segment in segments)
    ):
        raise ValueError("module_file_url")
    return f"{MOODLE_ORIGIN}{root}/pluginfile.php/{suffix}"


def _validate_mobile_tokens(webservice_token: str, private_token: str, course_id: int) -> None:
    if (
        _MOBILE_TOKEN.fullmatch(webservice_token) is None
        or _MOBILE_TOKEN.fullmatch(private_token) is None
        or type(course_id) is not int
        or not 1 <= course_id <= 2_147_483_647
    ):
        raise ValueError("invalid Moodle file request")


def _validate_mobile_service_token(webservice_token: str) -> None:
    if _MOBILE_TOKEN.fullmatch(webservice_token) is None:
        raise ValueError("invalid Moodle webservice token")


def _validate_mobile_file_request(
    webservice_token: str,
    private_token: str,
    course_id: int,
    source_id: int,
) -> None:
    _validate_mobile_tokens(webservice_token, private_token, course_id)
    if type(source_id) is not int or not 1 <= source_id <= 2_147_483_647:
        raise ValueError("invalid Moodle file request")


def _candidate_url(value: object, root: str, module: str, source_id: int) -> str:
    if value is None:
        return f"{MOODLE_ORIGIN}{root}/mod/{module}/view.php?id={source_id}"
    if not isinstance(value, str):
        raise ValueError("course_module_url_type")
    if len(value) > 2_048:
        raise ValueError("course_module_url_length")
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise ValueError("course_module_url_scheme")
    if parsed.netloc != "virtual.ufmg.br":
        raise ValueError("course_module_url_authority")
    if parsed.path != f"{root}/mod/{module}/view.php":
        raise ValueError(f"course_module_url_path_{module}")
    if parsed.fragment:
        raise ValueError("course_module_url_fragment")
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        raise ValueError("course_module_url_query_format") from None
    if set(query) != {"id"}:
        raise ValueError("course_module_url_query_keys")
    if query["id"] != [str(source_id)]:
        raise ValueError("course_module_url_query_id")
    return value


def _candidate_relevance(title: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", title).lower()
        if not unicodedata.combining(character)
    )
    if "plano de ensino" in normalized or "ementa" in normalized:
        return "teaching_plan"
    if "cronograma" in normalized or "calendario" in normalized:
        return "schedule"
    return "other"


def _require_identity_provider(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.hostname == "sistemas.ufmg.br" and parsed.path == "/idp/login.jsp":
        raise UFMGReauthenticationRequired("UFMG reauthentication required")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sistemas.ufmg.br"
        or not parsed.path.startswith("/idp/")
    ):
        raise UFMGReauthenticationRequired("UFMG reauthentication required")


def _require_moodle_acs(url: str, root: str) -> None:
    parsed = urlsplit(url)
    allowed_paths = {
        "/samlsso",
        "/Shibboleth.sso/SAML2/POST",
        f"{root}/Shibboleth.sso/SAML2/POST",
    }
    if parsed.scheme == "https" and parsed.hostname == "virtual.ufmg.br":
        if parsed.path in allowed_paths:
            return
        if parsed.path.rstrip("/") in allowed_paths:
            raise InvalidMoodleResponse("sso_redirect_trailing_slash")
        if re.fullmatch(r"/20[2-9][0-9][12]/Shibboleth[.]sso/SAML2/POST", parsed.path):
            raise InvalidMoodleResponse("sso_redirect_term_mismatch")
        raise InvalidMoodleResponse("sso_redirect_path")
    if not parsed.scheme and not parsed.netloc:
        reason = (
            "sso_redirect_relative_known"
            if parsed.path in allowed_paths
            else "sso_redirect_relative_other"
        )
        raise InvalidMoodleResponse(reason)
    if parsed.scheme != "https":
        raise InvalidMoodleResponse("sso_redirect_scheme")
    raise InvalidMoodleResponse("sso_redirect_host")


def _require_moodle_page(url: str, root: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "virtual.ufmg.br"
        or not parsed.path.startswith(f"{root}/")
    ):
        raise UFMGReauthenticationRequired("UFMG reauthentication required")


def _is_moodle_module(url: str, path: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "virtual.ufmg.br"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == path
        and not parsed.fragment
    )


def _is_diario_url(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 8_192:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "sistemas.ufmg.br"
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == "/diario/JasperServlet"
        and not parsed.fragment
    )


def _is_diario_launch_url(value: object) -> bool:
    if _is_diario_url(value):
        return True
    return _is_diario_request_url(value)


def _is_diario_request_url(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 8_192:
        return False
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sistemas.ufmg.br"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ("/diario/planoAula/relatorio/solicitar/solicitarRelatorioPlanoEnsino.do")
        or parsed.fragment
    ):
        return False
    try:
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    patterns = {
        "plt": r"[0-9]{5}",
        "oft": r"[0-9]{1,12}",
        "tac": r"[A-Za-z0-9_-]{1,16}",
        "aac": r"[A-Za-z0-9_.-]{1,32}",
        "trm": r"[A-Za-z0-9_.-]{1,32}",
    }
    return query.keys() == patterns.keys() and all(
        len(query[name]) == 1 and re.fullmatch(pattern, query[name][0]) is not None
        for name, pattern in patterns.items()
    )


def _diario_transition_target(body: bytes, source_url: str) -> str:
    markup = _decode_diario_html(body, reason="diario_transition_encoding")
    targets: set[str] = set()
    for raw in re.findall(r"""["']([^"']{1,8192})["']""", markup):
        candidate = urljoin(source_url, raw)
        if _is_diario_url(candidate):
            targets.add(candidate)
    if len(targets) != 1:
        reason = "diario_transition_targets" if targets else "diario_transition_target"
        raise InvalidMoodleResponse(reason)
    return next(iter(targets))


def _decode_diario_html(body: bytes, *, reason: str) -> str:
    """Decode HTML emitted by the legacy Diário application."""

    for encoding in ("utf-8", "windows-1252"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InvalidMoodleResponse(reason)


class _DiarioReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def is_plan(self) -> bool:
        raw_text = " ".join(" ".join(self._parts).split()).casefold()
        text = "".join(
            character
            for character in unicodedata.normalize("NFKD", raw_text)
            if not unicodedata.combining(character)
        )
        required = (
            "universidade federal de minas gerais",
            "plano de ensino",
            "periodo:",
            "atividade:",
        )
        return all(marker in text for marker in required) and (
            "cronograma" in text or "avaliacoes" in text
        )


def _require_diario_document(url: str, content_type: str, body: bytes) -> str:
    if content_type == "application/pdf":
        _require_diario_pdf(url, content_type, body)
        return "pdf"
    parsed = urlsplit(url)
    if parsed.hostname == "sistemas.ufmg.br" and parsed.path == "/idp/login.jsp":
        raise UFMGReauthenticationRequired("UFMG reauthentication required")
    if not _is_diario_url(url):
        raise InvalidMoodleResponse("diario_response_url")
    if content_type != "text/html":
        raise InvalidMoodleResponse("diario_response_type")
    parser = _DiarioReportParser()
    parser.feed(_decode_diario_html(body, reason="diario_response_encoding"))
    if not parser.is_plan():
        raise InvalidMoodleResponse("diario_response_html")
    return "html"


def _require_diario_pdf(url: str, content_type: str, body: bytes) -> None:
    parsed = urlsplit(url)
    if parsed.hostname == "sistemas.ufmg.br" and parsed.path == "/idp/login.jsp":
        raise UFMGReauthenticationRequired("UFMG reauthentication required")
    if not _is_diario_url(url):
        raise InvalidMoodleResponse("diario_response_url")
    if content_type != "application/pdf":
        raise InvalidMoodleResponse("diario_response_type")
    if len(body) < 9 or not body.startswith(b"%PDF-") or b"%%EOF" not in body[-1_024:]:
        raise InvalidMoodleResponse("diario_response_pdf")


def _require_ajax(url: str, content_type: str, ajax_path: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "virtual.ufmg.br" or parsed.path != ajax_path:
        raise UFMGReauthenticationRequired("UFMG reauthentication required")
    if content_type != "application/json":
        raise InvalidMoodleResponse("ajax_content_type")


def _mobile_tokens(callback: str, root: str, passport: str) -> tuple[str, str | None]:
    prefix = "moodlemobile://token="
    if not callback.startswith(prefix):
        raise InvalidMoodleResponse("mobile_callback_origin")
    try:
        decoded = b64decode(callback.removeprefix(prefix), validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        raise InvalidMoodleResponse("mobile_callback_encoding") from None
    parts = decoded.split(":::")
    if len(parts) not in {2, 3}:
        raise InvalidMoodleResponse("mobile_callback_shape")
    expected_site = md5(f"{MOODLE_ORIGIN}{root}{passport}".encode()).hexdigest()
    if parts[0] != expected_site:
        raise InvalidMoodleResponse("mobile_callback_site")
    if _MOBILE_TOKEN.fullmatch(parts[1]) is None:
        raise InvalidMoodleResponse("mobile_webservice_token")
    private_token = parts[2] if len(parts) == 3 else None
    if private_token is not None and _MOBILE_TOKEN.fullmatch(private_token) is None:
        raise InvalidMoodleResponse("mobile_private_token")
    return parts[1], private_token


def _require_json_endpoint(url: str, content_type: str, path: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "virtual.ufmg.br" or parsed.path != path:
        raise InvalidMoodleResponse("site_info_redirect")
    if content_type != "application/json":
        raise InvalidMoodleResponse("site_info_content_type")


def _moodle_root(term: str) -> str:
    if re.fullmatch(r"20[2-9][0-9]-[12]", term) is None:
        raise ValueError("invalid Moodle term")
    return f"/{term.replace('-', '')}"


def _token_digest(token: str) -> bytes:
    """Session-scoped cache key component; never logged or persisted."""
    return sha256(token.encode()).digest()


def _ltpa_cookie(token: str) -> Cookie:
    return Cookie(
        version=0,
        name="LtpaToken2",
        value=token,
        port=None,
        port_specified=False,
        domain=".sistemas.ufmg.br",
        domain_specified=True,
        domain_initial_dot=True,
        path="/",
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": "true"},
        rfc2109=False,
    )


def _ltpa_cookie_placeholder() -> Cookie:
    return _ltpa_cookie("placeholder")
