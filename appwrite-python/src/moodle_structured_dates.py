"""Read bounded, structured Moodle calendar data through the UFMG SSO session."""

import json
import re
import unicodedata
from collections.abc import Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ufmg_session_store import UFMGReauthenticationRequired

MAX_RESPONSE_BYTES = 1_048_576
MAX_EVENTS = 500
MAX_MONTHS = 12
MAX_COURSES = 50
MAX_CANDIDATES = 500
MOODLE_ORIGIN = "https://virtual.ufmg.br"
_SESSKEY = re.compile(rb'"sesskey"\s*:\s*"([A-Za-z0-9_-]{8,128})"')


class InvalidMoodleResponse(Exception):
    """Moodle or the identity provider returned an unsafe/unexpected shape."""

    def __init__(self, reason: str = "unknown") -> None:
        self.reason = reason if re.fullmatch(r"[a-z_]{1,64}", reason) else "unknown"
        super().__init__("invalid Moodle response")


class MoodleUnavailable(Exception):
    """The structured Moodle source could not be reached."""


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
        matched: list[tuple[str, dict[str, object]]] = []
        results: dict[str, dict[str, object]] = {}
        for code in codes:
            matches = [course for course in courses if _course_matches(code, course)]
            if len(matches) == 1:
                matched.append((code, matches[0]))
            else:
                results[code] = {
                    "course_code": code,
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
                for index, (_, course) in enumerate(matched)
            ]
            states = _parse_course_states(
                self._ajax(root, ajax_path, sesskey, state_calls),
                root,
                len(matched),
            )
            total = 0
            for (code, _), candidates in zip(matched, states, strict=True):
                total += len(candidates)
                if total > MAX_CANDIDATES:
                    raise InvalidMoodleResponse("candidate_limit")
                results[code] = {
                    "course_code": code,
                    "status": "found" if candidates else "empty",
                    "candidates": candidates,
                }
        return [results[code] for code in codes]

    def _connect(self, token: str, term: str) -> tuple[str, str, str]:
        _validate_token(token)
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
        return root, ajax_path, match.group(1).decode()

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
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                url = response.geturl()
                content_type = response.headers.get_content_type()
        except OSError:
            raise MoodleUnavailable("Moodle is unavailable") from None
        if len(body) > MAX_RESPONSE_BYTES:
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


def _require_ajax(url: str, content_type: str, ajax_path: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "virtual.ufmg.br" or parsed.path != ajax_path:
        raise UFMGReauthenticationRequired("UFMG reauthentication required")
    if content_type != "application/json":
        raise InvalidMoodleResponse("ajax_content_type")


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
