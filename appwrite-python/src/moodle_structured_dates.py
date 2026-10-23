"""Read bounded, structured Moodle calendar data through the UFMG SSO session."""

import json
import re
import unicodedata
from base64 import b64decode
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import md5, sha256
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from secrets import token_hex
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from diario_teaching_plan import parse_teaching_plan_html
from ufmg_session_store import UFMGReauthenticationRequired

MAX_RESPONSE_BYTES = 1_048_576
MAX_EVENTS = 500
MAX_MONTHS = 12
MAX_COURSES = 50
MAX_CANDIDATES = 500
MAX_DIARIO_BYTES = 20 * 1_048_576
MOODLE_ORIGIN = "https://virtual.ufmg.br"
_SESSKEY = re.compile(rb'"sesskey"\s*:\s*"([A-Za-z0-9_-]{8,128})"')
_MOBILE_TOKEN = re.compile(r"[A-Za-z0-9]{16,256}")
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class InvalidMoodleResponse(Exception):
    """Moodle or the identity provider returned an unsafe/unexpected shape."""

    def __init__(self, reason: str = "unknown") -> None:
        self.reason = reason if re.fullmatch(r"[a-z_]{1,64}", reason) else "unknown"
        super().__init__("invalid Moodle response")


class MoodleUnavailable(Exception):
    """The structured Moodle source could not be reached."""


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

    def __init__(
        self,
        *,
        opener: _Opener | None = None,
        timeout_seconds: float = 12,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("invalid Moodle timeout")
        self._timeout = timeout_seconds
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
            for index, (year, month) in enumerate(months)
        ]
        return _parse_calendar(
            self._ajax(root, ajax_path, sesskey, calls),
            len(calls),
        )

    def discover(
        self,
        token: str,
        *,
        term: str,
        course_codes: list[str],
    ) -> list[dict[str, object]]:
        """Discover bounded visible course resources without downloading content."""

        codes = _validate_course_codes(token, course_codes)
        root, ajax_path, sesskey = self._connect(token, term)
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
        courses = _parse_course_list(self._ajax(root, ajax_path, sesskey, course_call))
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
                    (code, course, "metaturma")
                    for course in matches
                    if _is_metaturma(course)
                )
            else:
                results[code] = {
                    "course_code": code,
                    "moodle_course_id": None,
                    "status": "ambiguous" if matches else "unmatched",
                    "candidates": [],
                }

        if matched:
            state_calls = [
                {
                    "index": index,
                    "methodname": "core_courseformat_get_state",
                    "args": {"courseid": course["id"]},
                }
                for index, (_, course, _) in enumerate(matched)
            ]
            states = _parse_course_states(
                self._ajax(root, ajax_path, sesskey, state_calls),
                root,
                len(matched),
            )
            total = 0
            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            for (code, course, origin), candidates in zip(matched, states, strict=True):
                total += len(candidates)
                if total > MAX_CANDIDATES:
                    raise InvalidMoodleResponse("candidate_limit")
                grouped[code].extend(
                    candidate
                    | {"origin": origin, "moodle_course_id": str(course["id"])}
                    for candidate in candidates
                )
            for code, candidates in grouped.items():
                results[code] = {
                    "course_code": code,
                    "moodle_course_id": results[code]["moodle_course_id"],
                    "status": "found" if candidates else "empty",
                    "candidates": candidates,
                }
        return [results[code] for code in codes]

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
            if isinstance(site_private_token, str)
            and _MOBILE_TOKEN.fullmatch(site_private_token)
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
        return _parse_module_files(
            payload,
            root=root,
            source_id=source_id,
            private_token=private_token,
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

    def fetch_diario_plan(
        self, token: str, *, term: str, source_id: int
    ) -> dict[str, object]:
        """Fetch and structure one official HTML teaching plan in memory."""

        _, body, document_format = self._fetch_diario_document(
            token, term=term, source_id=source_id
        )
        if document_format != "html":
            raise InvalidMoodleResponse("diario_plan_pdf_unstructured")
        try:
            result = parse_teaching_plan_html(
                _decode_diario_html(body, reason="diario_response_encoding")
            )
        except ValueError:
            raise InvalidMoodleResponse("diario_plan_structure") from None
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
        token_digest = sha256(token.encode()).digest()
        if token_digest != self._connection_token_digest:
            self._connections.clear()
            self._connection_token_digest = token_digest
        cached = self._connections.get(term)
        if cached is not None:
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
        return payload

    def _open(self, request: Request) -> tuple[bytes, str, str]:
        return self._open_bounded(request, limit=MAX_RESPONSE_BYTES)

    def _open_bounded(self, request: Request, *, limit: int) -> tuple[bytes, str, str]:
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(limit + 1)
                url = response.geturl()
                content_type = response.headers.get_content_type()
        except OSError:
            raise MoodleUnavailable("Moodle is unavailable") from None
        if len(body) > limit:
            raise InvalidMoodleResponse("response_oversized")
        return body, url, content_type


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


def _parse_course_states(
    payload: bytes,
    root: str,
    expected_calls: int,
) -> list[list[dict[str, object]]]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("course_state_json") from None
    if not isinstance(decoded, list):
        raise InvalidMoodleResponse("course_state_batch_type")
    if len(decoded) != expected_calls:
        raise InvalidMoodleResponse("course_state_call_count")
    states: list[list[dict[str, object]]] = []
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
            candidates: dict[str, dict[str, object]] = {}
            for raw in raw_modules:
                if not isinstance(raw, dict):
                    raise ValueError("course_module_shape")
                if raw.get("uservisible") is not True:
                    continue
                module = str(raw.get("module"))
                kind = {
                    "page": "page",
                    "book": "page",
                    "resource": "file",
                    "folder": "file",
                    "label": "text",
                    "url": "link",
                }.get(module)
                if kind is None:
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
                candidate: dict[str, object] = {
                    "source_id": str(source_id),
                    "kind": kind,
                    "title": title,
                    "url": None
                    if module == "label"
                    else _candidate_url(raw.get("url"), root, str(module), source_id),
                    "relevance": _candidate_relevance(title),
                }
                previous = candidates.get(str(source_id))
                if previous is not None and previous != candidate:
                    raise ValueError("course_module_conflict")
                candidates[str(source_id)] = candidate
            states.append(
                sorted(
                    candidates.values(),
                    key=lambda candidate: (
                        int(str(candidate["source_id"])),
                        str(candidate["title"]),
                    ),
                )
            )
    except (KeyError, TypeError, ValueError) as error:
        reason = str(error) if error.args else "course_state_shape"
        raise InvalidMoodleResponse(reason) from None
    return states


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
    return (
        f"{MOODLE_ORIGIN}{root}/tokenpluginfile.php/{private_token}/{suffix}"
        "?forcedownload=1"
    )


def _validate_mobile_file_request(
    webservice_token: str,
    private_token: str,
    course_id: int,
    source_id: int,
) -> None:
    if (
        _MOBILE_TOKEN.fullmatch(webservice_token) is None
        or _MOBILE_TOKEN.fullmatch(private_token) is None
        or type(course_id) is not int
        or not 1 <= course_id <= 2_147_483_647
        or type(source_id) is not int
        or not 1 <= source_id <= 2_147_483_647
    ):
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
        or parsed.path
        != (
            "/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do"
        )
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
    for raw in re.findall(r'''["']([^"']{1,8192})["']''', markup):
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
