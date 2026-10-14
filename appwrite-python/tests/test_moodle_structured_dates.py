import json
from email.message import Message
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import moodle_structured_dates as module
from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
    _candidate_relevance,
    _candidate_url,
    _course_matches,
    _event,
    _parse_calendar,
    _parse_course_list,
    _parse_course_states,
    _require_ajax,
    _require_moodle_acs,
    _require_moodle_page,
    _SAMLFormParser,
    _validate_course_codes,
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
      <form method="post" action="https://virtual.ufmg.br/samlsso">
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


def _course_list_response() -> bytes:
    return json.dumps(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        {
                            "id": 3701,
                            "shortname": "DCC203 - POO",
                            "fullname": "Programação Orientada a Objetos",
                        },
                        {
                            "id": 4953,
                            "shortname": "MAT001",
                            "fullname": "Cálculo",
                        },
                        {
                            "id": 9999,
                            "shortname": "OUTRA",
                            "fullname": "Outra disciplina",
                        },
                    ],
                    "nextoffset": 3,
                },
            }
        ]
    ).encode()


def _course_state_response() -> bytes:
    dcc203 = {
        "course": {},
        "section": [],
        "cm": [
            {
                "id": 101,
                "name": "Plano de ensino",
                "module": "page",
                "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                "uservisible": True,
            },
            {
                "id": 102,
                "name": "Cronograma da disciplina.pdf",
                "module": "resource",
                "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=102",
                "uservisible": True,
            },
            {
                "id": 103,
                "name": "Orientações gerais",
                "module": "label",
                "uservisible": True,
            },
            {
                "id": 104,
                "name": "Trabalho 1",
                "module": "assign",
                "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=104",
                "uservisible": True,
            },
        ],
    }
    empty = {"course": {}, "section": [], "cm": []}
    return json.dumps(
        [
            {"error": False, "data": json.dumps(dcc203)},
            {"error": False, "data": json.dumps(empty)},
        ]
    ).encode()


def test_client_discovers_pages_files_text_and_empty_courses() -> None:
    opener = _Opener(
        [
            _Response(
                _saml_page(),
                "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO",
            ),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _course_list_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
            _Response(
                _course_state_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).discover(
        "private-ltpa-token",
        term="2026-2",
        course_codes=["DCC203", "ELE028", "MAT001"],
    )

    assert result == [
        {
            "course_code": "DCC203",
            "status": "found",
            "candidates": [
                {
                    "source_id": "101",
                    "kind": "page",
                    "title": "Plano de ensino",
                    "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                    "relevance": "teaching_plan",
                },
                {
                    "source_id": "102",
                    "kind": "file",
                    "title": "Cronograma da disciplina.pdf",
                    "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=102",
                    "relevance": "schedule",
                },
                {
                    "source_id": "103",
                    "kind": "text",
                    "title": "Orientações gerais",
                    "url": None,
                    "relevance": "other",
                },
            ],
        },
        {"course_code": "ELE028", "status": "unmatched", "candidates": []},
        {"course_code": "MAT001", "status": "empty", "candidates": []},
    ]
    assert len(opener.requests) == 4
    course_call = json.loads(opener.requests[2][0].data)[0]
    assert course_call["methodname"] == (
        "core_course_get_enrolled_courses_by_timeline_classification"
    )
    assert course_call["args"] == {
        "classification": "all",
        "limit": 100,
        "offset": 0,
        "sort": "fullname ASC",
    }
    state_calls = json.loads(opener.requests[3][0].data)
    assert [call["args"] for call in state_calls] == [
        {"courseid": 3701},
        {"courseid": 4953},
    ]


def test_discovery_skips_course_state_call_when_nothing_matches() -> None:
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _course_list_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    )
    assert (
        MoodleStructuredDatesClient(opener=opener).discover(
            "token", term="2026-2", course_codes=["ELE028"]
        )[0]["status"]
        == "unmatched"
    )
    assert len(opener.requests) == 3


def test_discovery_enforces_the_global_candidate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    courses = json.dumps(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        {"id": 1, "shortname": "AAA1", "fullname": "A"},
                        {"id": 2, "shortname": "BBB2", "fullname": "B"},
                    ],
                    "nextoffset": 2,
                },
            }
        ]
    ).encode()
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                courses,
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
            _Response(
                b"[]",
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    )
    candidate = {"source_id": "1", "kind": "text", "title": "X", "url": None, "relevance": "other"}
    monkeypatch.setattr(module, "_parse_course_states", lambda *_: [[candidate] * 500, [candidate]])
    with pytest.raises(InvalidMoodleResponse) as error:
        MoodleStructuredDatesClient(opener=opener).discover(
            "token", term="2026-2", course_codes=["AAA1", "BBB2"]
        )
    assert error.value.reason == "candidate_limit"


@pytest.mark.parametrize(
    "codes",
    [[], ["A"] * 51, ["DCC203", "DCC203"], [""], [" dcc203"], ["x" * 33], ["A B"]],
)
def test_discovery_rejects_invalid_course_code_sets(codes: list[str]) -> None:
    with pytest.raises(ValueError):
        _validate_course_codes("token", codes)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({}).encode(),
        json.dumps([]).encode(),
        json.dumps([None]).encode(),
        json.dumps([{"error": True}]).encode(),
        json.dumps([{"error": False, "data": None}]).encode(),
        json.dumps([{"error": False, "data": {"courses": None, "nextoffset": 0}}]).encode(),
        json.dumps([{"error": False, "data": {"courses": [], "nextoffset": -1}}]).encode(),
        json.dumps([{"error": False, "data": {"courses": [None], "nextoffset": 1}}]).encode(),
        json.dumps(
            [
                {
                    "error": False,
                    "data": {
                        "courses": [{"id": 0, "shortname": "X", "fullname": "Y"}],
                        "nextoffset": 1,
                    },
                }
            ]
        ).encode(),
        json.dumps(
            [
                {
                    "error": False,
                    "data": {
                        "courses": [
                            {"id": 1, "shortname": "X", "fullname": "Y"},
                            {"id": 1, "shortname": "Z", "fullname": "Y"},
                        ],
                        "nextoffset": 2,
                    },
                }
            ]
        ).encode(),
    ],
)
def test_course_list_parser_rejects_malformed_or_conflicting_data(payload: bytes) -> None:
    with pytest.raises(InvalidMoodleResponse):
        _parse_course_list(payload)


def test_course_list_parser_deduplicates_and_matcher_uses_code_boundaries() -> None:
    course = {"id": 1, "shortname": "POO DCC203", "fullname": "Objetos"}
    payload = json.dumps(
        [{"error": False, "data": {"courses": [course, course], "nextoffset": 2}}]
    ).encode()
    assert _parse_course_list(payload) == [course]
    assert _course_matches("DCC203", course)
    assert not _course_matches("DCC20", course)


@pytest.mark.parametrize(
    "payload,expected_calls",
    [
        (b"bad", 1),
        (json.dumps({}).encode(), 1),
        (json.dumps([]).encode(), 1),
        (json.dumps([None]).encode(), 1),
        (json.dumps([{"error": True}]).encode(), 1),
        (json.dumps([{"error": False, "data": None}]).encode(), 1),
        (json.dumps([{"error": False, "data": "bad"}]).encode(), 1),
        (json.dumps([{"error": False, "data": "[]"}]).encode(), 1),
        (json.dumps([{"error": False, "data": json.dumps({"cm": None})}]).encode(), 1),
        (json.dumps([{"error": False, "data": json.dumps({"cm": [None]})}]).encode(), 1),
        (
            json.dumps(
                [
                    {
                        "error": False,
                        "data": json.dumps(
                            {
                                "cm": [
                                    {
                                        "id": 0,
                                        "name": "X",
                                        "module": "page",
                                        "url": "x",
                                        "uservisible": True,
                                    }
                                ]
                            }
                        ),
                    }
                ]
            ).encode(),
            1,
        ),
    ],
)
def test_course_state_parser_rejects_malformed_data(payload: bytes, expected_calls: int) -> None:
    with pytest.raises(InvalidMoodleResponse):
        _parse_course_states(payload, "/20262", expected_calls)


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"id": None}, "course_module_id_type"),
        ({"id": "01"}, "course_module_id_format"),
        ({"id": 0}, "course_module_id_range"),
        ({"id": 2_147_483_648}, "course_module_id_range"),
        ({"name": None}, "course_module_title_type"),
        ({"name": "   "}, "course_module_title_empty"),
        ({"name": "x" * 1_025}, "course_module_title_length"),
    ],
)
def test_course_state_parser_reports_safe_module_field_reason(
    overrides: dict[str, object], reason: str
) -> None:
    module = {
        "id": 1,
        "name": "Plano",
        "module": "page",
        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=1",
        "uservisible": True,
        **overrides,
    }
    payload = json.dumps([{"error": False, "data": json.dumps({"cm": [module]})}]).encode()

    with pytest.raises(InvalidMoodleResponse) as caught:
        _parse_course_states(payload, "/20262", 1)

    assert caught.value.reason == reason


def test_course_state_parser_canonicalizes_numeric_string_module_ids() -> None:
    module = {
        "id": "123",
        "name": "Plano",
        "module": "page",
        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=123",
        "uservisible": True,
    }
    payload = json.dumps([{"error": False, "data": json.dumps({"cm": [module]})}]).encode()

    result = _parse_course_states(payload, "/20262", 1)[0]

    assert result[0]["source_id"] == "123"


def test_course_state_parser_supports_all_candidate_modules_and_visibility() -> None:
    modules = [
        {
            "id": 1,
            "name": "Ementa",
            "module": "book",
            "url": "https://virtual.ufmg.br/20262/mod/book/view.php?id=1",
            "uservisible": True,
        },
        {
            "id": 2,
            "name": "Arquivos",
            "module": "folder",
            "url": "https://virtual.ufmg.br/20262/mod/folder/view.php?id=2",
            "uservisible": True,
        },
        {
            "id": 3,
            "name": "Oculto",
            "module": "page",
            "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=3",
            "uservisible": False,
        },
        {
            "id": 4,
            "name": "Fórum",
            "module": "forum",
            "url": "https://virtual.ufmg.br/20262/mod/forum/view.php?id=4",
            "uservisible": True,
        },
    ]
    payload = json.dumps([{"error": False, "data": json.dumps({"cm": modules})}]).encode()
    result = _parse_course_states(payload, "/20262", 1)[0]
    assert [item["kind"] for item in result] == ["page", "file"]
    assert result[0]["relevance"] == "teaching_plan"


def test_course_state_parser_normalizes_long_module_titles() -> None:
    title = "X" * 255
    module = {
        "id": 1,
        "name": f"  {title}  ",
        "module": "page",
        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=1",
        "uservisible": True,
    }
    payload = json.dumps([{"error": False, "data": json.dumps({"cm": [module]})}]).encode()

    result = _parse_course_states(payload, "/20262", 1)[0]

    assert result[0]["title"] == title


def test_course_state_parser_rejects_conflicting_ids_and_unsafe_urls() -> None:
    first = {
        "id": 1,
        "name": "Plano",
        "module": "page",
        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=1",
        "uservisible": True,
    }
    conflict = {**first, "name": "Outro"}
    for modules in ([first, conflict], [{**first, "url": "https://attacker.example/x?id=1"}]):
        payload = json.dumps([{"error": False, "data": json.dumps({"cm": modules})}]).encode()
        with pytest.raises(InvalidMoodleResponse):
            _parse_course_states(payload, "/20262", 1)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "x" * 2049,
        "http://virtual.ufmg.br/20262/mod/page/view.php?id=1",
        "https://virtual.ufmg.br/20262/mod/page/view.php?id=2",
        "https://virtual.ufmg.br/20262/mod/page/view.php?id=1#x",
    ],
)
def test_candidate_url_rejects_every_unsafe_shape(value: object) -> None:
    with pytest.raises(ValueError):
        _candidate_url(value, "/20262", "page", 1)


@pytest.mark.parametrize(
    "value,reason",
    [
        (None, "course_module_url_type"),
        ("x" * 2_049, "course_module_url_length"),
        ("http://virtual.ufmg.br/20262/mod/page/view.php?id=1", "course_module_url_scheme"),
        (
            "https://user@virtual.ufmg.br/20262/mod/page/view.php?id=1",
            "course_module_url_authority",
        ),
        ("https://virtual.ufmg.br/20262/mod/book/view.php?id=1", "course_module_url_path_page"),
        (
            "https://virtual.ufmg.br/20262/mod/page/view.php?id=1#x",
            "course_module_url_fragment",
        ),
        (
            "https://virtual.ufmg.br/20262/mod/page/view.php?id",
            "course_module_url_query_format",
        ),
        (
            "https://virtual.ufmg.br/20262/mod/page/view.php?id=1&extra=1",
            "course_module_url_query_keys",
        ),
        (
            "https://virtual.ufmg.br/20262/mod/page/view.php?id=2",
            "course_module_url_query_id",
        ),
    ],
)
def test_candidate_url_reports_only_a_safe_rejection_reason(value: object, reason: str) -> None:
    with pytest.raises(ValueError) as caught:
        _candidate_url(value, "/20262", "page", 1)

    assert str(caught.value) == reason


def test_candidate_relevance_handles_accents_and_other_titles() -> None:
    assert _candidate_relevance("Calendário") == "schedule"
    assert _candidate_relevance("Avisos") == "other"


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
        b"{}",
        b"[]",
        b"[null]",
        json.dumps([{"error": True, "exception": {"message": "private"}}]).encode(),
        json.dumps([{"error": False, "data": {"weeks": "bad"}}]).encode(),
        b"x" * 1_048_577,
    ],
    ids=[
        "invalid-json",
        "invalid-batch",
        "empty",
        "invalid-call",
        "upstream-error",
        "invalid-weeks",
        "oversized",
    ],
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


def test_invalid_moodle_reason_is_bounded_for_safe_logging() -> None:
    assert InvalidMoodleResponse("calendar_json").reason == "calendar_json"
    assert InvalidMoodleResponse("private upstream detail: secret").reason == "unknown"


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


def test_calendar_parser_ignores_events_without_a_course() -> None:
    response = json.loads(_calendar_response())[0]
    response["data"]["weeks"][0]["days"][0]["events"].insert(
        0,
        {
            "id": 909,
            "name": "Evento geral da universidade",
            "timestart": 1792105200,
            "eventtype": "site",
        },
    )

    events = _parse_calendar(json.dumps([response]).encode(), 1)

    assert [event["source_id"] for event in events] == ["910", "911"]


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


def test_moodle_acs_accepts_the_default_root_level_shibboleth_handler() -> None:
    _require_moodle_acs(
        "https://virtual.ufmg.br/Shibboleth.sso/SAML2/POST",
        "/20262",
    )


def test_moodle_acs_accepts_the_ufmg_saml_consumer() -> None:
    _require_moodle_acs("https://virtual.ufmg.br/samlsso", "/20262")


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (
            "http://virtual.ufmg.br/Shibboleth.sso/SAML2/POST",
            "sso_redirect_scheme",
        ),
        (
            "https://attacker.example/Shibboleth.sso/SAML2/POST",
            "sso_redirect_host",
        ),
        (
            "https://virtual.ufmg.br/Shibboleth.sso/SAML2/POST/",
            "sso_redirect_trailing_slash",
        ),
        (
            "https://virtual.ufmg.br/20261/Shibboleth.sso/SAML2/POST",
            "sso_redirect_term_mismatch",
        ),
        (
            "/20262/Shibboleth.sso/SAML2/POST",
            "sso_redirect_relative_known",
        ),
        (
            "https://virtual.ufmg.br/Shibboleth.sso/SAML2/POST/extra",
            "sso_redirect_path",
        ),
        (
            "https://virtual.ufmg.br/other/Shibboleth.sso/SAML2/POST",
            "sso_redirect_path",
        ),
    ],
)
def test_moodle_acs_rejects_every_other_origin_or_path(url: str, reason: str) -> None:
    with pytest.raises(InvalidMoodleResponse) as error:
        _require_moodle_acs(url, "/20262")
    assert error.value.reason == reason
