"""Read bounded, structured Moodle calendar data through the UFMG SSO session."""

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ufmg_session_store import UFMGReauthenticationRequired

MAX_RESPONSE_BYTES = 1_048_576
MAX_EVENTS = 500
MAX_MONTHS = 12
MOODLE_ORIGIN = "https://virtual.ufmg.br"
_SESSKEY = re.compile(rb'"sesskey"\s*:\s*"([A-Za-z0-9_-]{8,128})"')


class InvalidMoodleResponse(Exception):
    """Moodle or the identity provider returned an unsafe/unexpected shape."""


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
            raise InvalidMoodleResponse("invalid Moodle SSO response") from None
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
        sesskey = match.group(1).decode()

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
        ajax_url = f"{MOODLE_ORIGIN}{ajax_path}?" + urlencode(
            {
                "sesskey": sesskey,
                "info": ",".join("core_calendar_get_calendar_monthly_view" for _ in calls),
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
        return _parse_calendar(payload, len(calls))

    def _open(self, request: Request) -> tuple[bytes, str, str]:
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
                url = response.geturl()
                content_type = response.headers.get_content_type()
        except OSError:
            raise MoodleUnavailable("Moodle is unavailable") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise InvalidMoodleResponse("invalid Moodle response")
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
            raise InvalidMoodleResponse("invalid Moodle SSO response")
        return action, relay_state, assertion


def _parse_calendar(payload: bytes, expected_calls: int) -> list[dict[str, str]]:
    try:
        decoded = json.loads(payload)
        if (
            not isinstance(decoded, list)
            or len(decoded) != expected_calls
            or any(not isinstance(item, dict) or item.get("error") is not False for item in decoded)
        ):
            raise ValueError
        events: dict[str, dict[str, str]] = {}
        for item in decoded:
            data = item.get("data")
            if not isinstance(data, dict):
                raise ValueError
            for raw in _calendar_events(data):
                event = _event(raw)
                previous = events.get(event["source_id"])
                if previous is not None and previous != event:
                    raise ValueError
                events[event["source_id"]] = event
                if len(events) > MAX_EVENTS:
                    raise ValueError
        return sorted(events.values(), key=lambda item: (item["due_at"], item["source_id"]))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidMoodleResponse("invalid Moodle calendar response") from None


def _calendar_events(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    weeks = data.get("weeks")
    if not isinstance(weeks, list) or len(weeks) > 6:
        raise ValueError
    for week in weeks:
        if not isinstance(week, dict):
            raise ValueError
        days = week.get("days")
        if not isinstance(days, list) or len(days) > 7:
            raise ValueError
        for day in days:
            if not isinstance(day, dict):
                raise ValueError
            events = day.get("events", [])
            if not isinstance(events, list) or len(events) > 100:
                raise ValueError
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError
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
        raise ValueError
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
        raise ValueError
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


def _validate_inputs(token: str, months: list[tuple[int, int]]) -> None:
    if not token or len(token) > 4_096 or any(character.isspace() for character in token):
        raise ValueError("invalid UFMG session")
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
    if (
        parsed.scheme != "https"
        or parsed.hostname != "virtual.ufmg.br"
        or parsed.path != f"{root}/Shibboleth.sso/SAML2/POST"
    ):
        raise InvalidMoodleResponse("invalid Moodle SSO response")


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
        raise InvalidMoodleResponse("invalid Moodle calendar response")


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
