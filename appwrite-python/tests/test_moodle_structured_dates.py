import json
from email.message import Message
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
    _event,
    _parse_calendar,
    _require_ajax,
    _require_moodle_acs,
    _require_moodle_page,
    _SAMLFormParser,
)
from ufmg_session_store import UFMGReauthenticationRequired


class _Response:
    def __init__(
        self,
        body: bytes,
        url: str,
        *,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        self._body = body
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        assert limit == 1_048_577
        return self._body

    def geturl(self) -> str:
        return self._url


class _Opener:
    def __init__(self, responses: list[_Response | OSError]) -> None:
        self.responses = responses
        self.requests: list[tuple[Any, float]] = []

    def open(self, request: Any, *, timeout: float) -> _Response:
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, OSError):
            raise response
        return response


def _saml_page() -> bytes:
    return b"""
      <form method="post" action="https://virtual.ufmg.br/20262/Shibboleth.sso/SAML2/POST">
        <input type="hidden" name="RelayState" value="relay-safe">
        <input type="hidden" name="SAMLResponse" value="assertion-safe">
      </form>
    """


def _dashboard() -> bytes:
    return b'<script>M.cfg={"sesskey":"session-key-123"};</script>'


def _calendar_response() -> bytes:
    data = {
        "weeks": [
            {
                "days": [
                    {
                        "events": [
                            {
                                "id": 910,
                                "name": "Trabalho pr\u00e1tico 1",
                                "timestart": 1792710000,
                                "course": {
                                    "id": 3701,
                                    "shortname": "DCC203 - POO",
                                    "fullname": "Programa\u00e7\u00e3o Orientada a Objetos",
                                },
                                "modulename": "assign",
                            },
                            {
                                "id": 911,
                                "name": "Question\u00e1rio 2",
                                "timestart": 1793314800,
                                "course": {
                                    "id": 3701,
                                    "shortname": "DCC203 - POO",
                                    "fullname": "Programa\u00e7\u00e3o Orientada a Objetos",
                                },
                                "modulename": "quiz",
                            },
                        ]
                    }
                ]
            }
        ]
    }
    return json.dumps([{"error": False, "data": data}]).encode()


def test_client_completes_saml_and_returns_sanitized_structured_events() -> None:
    opener = _Opener(
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _calendar_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php?sesskey=session-key-123&info=core_calendar_get_calendar_monthly_view",
                content_type="application/json",
            ),
        ]
    )
    client = MoodleStructuredDatesClient(opener=opener, timeout_seconds=8)

    events = client.fetch("private-ltpa-token", term="2026-2", months=[(2026, 10)])

    assert events == [
        {
            "source_id": "910",
            "title": "Trabalho pr\u00e1tico 1",
            "due_at": "2026-10-22T23:00:00Z",
            "moodle_course_id": "3701",
            "course_shortname": "DCC203 - POO",
            "course_fullname": "Programa\u00e7\u00e3o Orientada a Objetos",
            "kind": "assignment",
        },
        {
            "source_id": "911",
            "title": "Question\u00e1rio 2",
            "due_at": "2026-10-29T23:00:00Z",
            "moodle_course_id": "3701",
            "course_shortname": "DCC203 - POO",
            "course_fullname": "Programa\u00e7\u00e3o Orientada a Objetos",
            "kind": "quiz",
        },
    ]
    assert len(opener.requests) == 3
    first, timeout = opener.requests[0]
    assert first.full_url == "https://virtual.ufmg.br/20262/auth/shibboleth/index.php"
    assert first.get_header("Cookie") is None
    assert timeout == 8
    saml_post, _ = opener.requests[1]
    assert saml_post.get_method() == "POST"
    assert parse_qs(saml_post.data.decode()) == {
        "RelayState": ["relay-safe"],
        "SAMLResponse": ["assertion-safe"],
    }
    ajax, _ = opener.requests[2]
    assert ajax.get_method() == "POST"
    body = json.loads(ajax.data)
    assert body[0]["methodname"] == "core_calendar_get_calendar_monthly_view"
    assert body[0]["args"] == {
        "year": 2026,
        "month": 10,
        "courseid": 1,
        "categoryid": 0,
        "includenavigation": False,
        "mini": False,
        "day": 1,
    }
    emitted = repr(events) + repr([(r.full_url, r.headers) for r, _ in opener.requests])
    assert "private-ltpa-token" not in emitted
    assert "assertion-safe" not in repr(events)


def test_client_declares_each_method_in_a_multi_month_ajax_batch() -> None:
    empty_month = {"weeks": []}
    opener = _Opener(
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                json.dumps(
                    [
                        {"error": False, "data": empty_month},
                        {"error": False, "data": empty_month},
                    ]
                ).encode(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    )

    assert (
        MoodleStructuredDatesClient(opener=opener).fetch(
            "private-ltpa-token", term="2026-2", months=[(2026, 10), (2026, 11)]
        )
        == []
    )

    ajax_url = opener.requests[2][0].full_url
    assert parse_qs(urlsplit(ajax_url).query)["info"] == [
        "core_calendar_get_calendar_monthly_view,core_calendar_get_calendar_monthly_view"
    ]


@pytest.mark.parametrize(
    "responses,exception",
    [
        ([OSError()], MoodleUnavailable),
        (
            [_Response(b"login", "https://sistemas.ufmg.br/idp/login.jsp")],
            UFMGReauthenticationRequired,
        ),
        (
            [_Response(b"<html></html>", "https://attacker.example/idp/")],
            UFMGReauthenticationRequired,
        ),
        (
            [
                _Response(
                    (
                        b'<form action="https://attacker.example/steal">'
                        b'<input name="SAMLResponse" value="x">'
                        b'<input name="RelayState" value="y"></form>'
                    ),
                    "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
                )
            ],
            InvalidMoodleResponse,
        ),
    ],
)
def test_client_fails_closed_for_network_login_and_untrusted_redirects(
    responses: list[_Response | OSError], exception: type[Exception]
) -> None:
    with pytest.raises(exception):
        MoodleStructuredDatesClient(opener=_Opener(responses)).fetch(
            "private-token", term="2026-2", months=[(2026, 10)]
        )


@pytest.mark.parametrize(
    "months",
    [[], [(2026, 0)], [(2026, 13)], [(2025, 1)] * 13],
)
def test_client_rejects_unbounded_month_ranges(months: list[tuple[int, int]]) -> None:
    with pytest.raises(ValueError):
        MoodleStructuredDatesClient(opener=_Opener([])).fetch(
            "private-token", term="2026-2", months=months
        )


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        json.dumps([{"error": True, "exception": {"message": "private"}}]).encode(),
        json.dumps([{"error": False, "data": {"weeks": "bad"}}]).encode(),
        b"x" * 1_048_577,
    ],
    ids=["invalid-json", "empty", "upstream-error", "invalid-weeks", "oversized"],
)
def test_client_rejects_malformed_calendar_without_exposing_upstream_details(
    payload: bytes,
) -> None:
    opener = _Opener(
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                payload,
                "https://virtual.ufmg.br/20262/lib/ajax/service.php?sesskey=session-key-123&info=core_calendar_get_calendar_monthly_view",
                content_type="application/json",
            ),
        ]
    )

    with pytest.raises(InvalidMoodleResponse) as error:
        MoodleStructuredDatesClient(opener=opener).fetch(
            "private-token", term="2026-2", months=[(2026, 10)]
        )

    assert "private" not in str(error.value)


def test_default_cookie_jar_scopes_the_private_token_and_can_use_injected_io() -> None:
    client = MoodleStructuredDatesClient()
    opener = _Opener(
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _calendar_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php?safe=1",
                content_type="application/json",
            ),
        ]
    )
    client._opener = opener

    assert len(client.fetch("private-token", term="2026-2", months=[(2026, 10)])) == 2
    assert client._jar is not None
    cookies = list(client._jar)
    assert [(cookie.name, cookie.domain, cookie.secure) for cookie in cookies] == [
        ("LtpaToken2", ".sistemas.ufmg.br", True)
    ]


def test_client_rejects_invalid_utf8_missing_session_and_invalid_final_page() -> None:
    cases = [
        [
            _Response(
                b"\xff",
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            )
        ],
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(b"no sesskey", "https://virtual.ufmg.br/20262/my/"),
        ],
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://attacker.example/20262/my/"),
        ],
    ]
    expected = [InvalidMoodleResponse, UFMGReauthenticationRequired, UFMGReauthenticationRequired]
    for responses, exception in zip(cases, expected, strict=True):
        with pytest.raises(exception):
            MoodleStructuredDatesClient(opener=_Opener(responses)).fetch(
                "private-token", term="2026-2", months=[(2026, 10)]
            )


def test_saml_parser_ignores_irrelevant_tags_and_rejects_incomplete_forms() -> None:
    parser = _SAMLFormParser()
    parser.feed(
        '<input name="RelayState" value="outside"><form method="get"></form>'
        '<form method="post"><input name="ignored"><span></span></form>'
    )
    parser.handle_endtag("div")
    with pytest.raises(InvalidMoodleResponse):
        parser.result()


@pytest.mark.parametrize(
    "payload",
    [
        [{"error": False, "data": {"weeks": [None]}}],
        [{"error": False, "data": None}],
        [{"error": False, "data": {"weeks": [{"days": None}]}}],
        [{"error": False, "data": {"weeks": [{"days": [None]}]}}],
        [
            {
                "error": False,
                "data": {"weeks": [{"days": [{"events": [None]}]}]},
            }
        ],
        [{"error": False, "data": {"weeks": [None] * 7}}],
        [
            {
                "error": False,
                "data": {"weeks": [{"days": [None] * 8}]},
            }
        ],
        [
            {
                "error": False,
                "data": {"weeks": [{"days": [{"events": [None] * 101}]}]},
            }
        ],
    ],
)
def test_calendar_parser_rejects_each_nested_boundary(payload: object) -> None:
    with pytest.raises(InvalidMoodleResponse):
        _parse_calendar(json.dumps(payload).encode(), 1)


def test_calendar_parser_deduplicates_identical_events_and_rejects_conflicts() -> None:
    response = json.loads(_calendar_response())[0]
    event = response["data"]["weeks"][0]["days"][0]["events"][0]
    response["data"]["weeks"][0]["days"][0]["events"].append(dict(event))
    assert len(_parse_calendar(json.dumps([response]).encode(), 1)) == 2
    response["data"]["weeks"][0]["days"][0]["events"][-1]["name"] = "Conflito"
    with pytest.raises(InvalidMoodleResponse):
        _parse_calendar(json.dumps([response]).encode(), 1)


def test_calendar_parser_rejects_more_than_the_global_event_limit() -> None:
    template = json.loads(_calendar_response())[0]["data"]["weeks"][0]["days"][0]["events"][0]
    events = [{**template, "id": index + 1} for index in range(501)]
    days = [{"events": events[index : index + 100]} for index in range(0, 501, 100)]
    payload = [{"error": False, "data": {"weeks": [{"days": days}]}}]
    with pytest.raises(InvalidMoodleResponse):
        _parse_calendar(json.dumps(payload).encode(), 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"id": 0},
        {"name": ""},
        {"name": " x"},
        {"name": "x" * 121},
        {"timestart": 0},
        {"course": None},
        {"course": {"id": 0, "shortname": "X", "fullname": "Y"}},
        {"course": {"id": 1, "shortname": "", "fullname": "Y"}},
        {"course": {"id": 1, "shortname": "X", "fullname": "Y "}},
    ],
)
def test_event_parser_rejects_invalid_values(changes: dict[str, object]) -> None:
    raw = json.loads(_calendar_response())[0]["data"]["weeks"][0]["days"][0]["events"][0]
    raw.update(changes)
    with pytest.raises(ValueError):
        _event(raw)


def test_event_parser_classifies_unknown_or_missing_modules_as_events() -> None:
    raw = json.loads(_calendar_response())[0]["data"]["weeks"][0]["days"][0]["events"][0]
    raw["modulename"] = None
    assert _event(raw)["kind"] == "event"


@pytest.mark.parametrize("token", ["", "has space", "x" * 4097])
def test_client_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        MoodleStructuredDatesClient(opener=_Opener([])).fetch(
            token, term="2026-2", months=[(2026, 10)]
        )


def test_client_rejects_an_invalid_moodle_term() -> None:
    with pytest.raises(ValueError):
        MoodleStructuredDatesClient(opener=_Opener([])).fetch(
            "private-token", term="2026-3", months=[(2026, 10)]
        )


def test_client_rejects_invalid_timeout_and_ajax_boundaries() -> None:
    with pytest.raises(ValueError):
        MoodleStructuredDatesClient(timeout_seconds=31)
    with pytest.raises(UFMGReauthenticationRequired):
        _require_moodle_page("http://virtual.ufmg.br/20262/my/", "/20262")
    with pytest.raises(InvalidMoodleResponse):
        _require_moodle_acs("https://attacker.example/steal", "/20262")
    with pytest.raises(UFMGReauthenticationRequired):
        _require_ajax(
            "https://attacker.example/20262/lib/ajax/service.php",
            "application/json",
            "/20262/lib/ajax/service.php",
        )
    with pytest.raises(InvalidMoodleResponse):
        _require_ajax(
            "https://virtual.ufmg.br/20262/lib/ajax/service.php",
            "text/html",
            "/20262/lib/ajax/service.php",
        )
