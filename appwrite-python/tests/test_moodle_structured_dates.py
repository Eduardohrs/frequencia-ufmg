import json
from base64 import b64decode, b64encode
from email.message import Message
from hashlib import md5
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

import moodle_structured_dates as module
from moodle_structured_dates import (
    DiarioPlanProbe,
    InvalidMoodleResponse,
    MoodleMobileAuthorization,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
    _candidate_relevance,
    _candidate_url,
    _course_matches,
    _diario_transition_target,
    _DiarioFormParser,
    _event,
    _is_diario_launch_url,
    _is_diario_url,
    _is_metaturma,
    _is_moodle_module,
    _mobile_tokens,
    _parse_calendar,
    _parse_course_list,
    _parse_course_states,
    _parse_module_files,
    _require_ajax,
    _require_diario_document,
    _require_diario_pdf,
    _require_json_endpoint,
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
        assert limit in {1_048_577, 20 * 1_048_576 + 1}
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


def _diario_pdf() -> bytes:
    return b"%PDF-1.7\nvalidated plan\n%%EOF"


def _diario_html() -> bytes:
    return b"""
      <html><body>
        <h1>Universidade Federal de Minas Gerais</h1>
        <p>Diario de Classe</p>
        <h2>Plano de Ensino</h2>
        <p>Periodo: 2026/2</p>
        <p>Atividade: ELE631</p>
        <h3>Cronograma</h3>
      </body></html>
    """


def test_diario_probe_accepts_a_direct_pdf_redirect_without_exposing_parameters() -> None:
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _diario_pdf(),
                "https://sistemas.ufmg.br/diario/JasperServlet?private=course",
                content_type="application/pdf",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).probe_diario_plan(
        "token-safe", term="2026-2", source_id=99
    )

    assert result == DiarioPlanProbe(delivery="redirect", content_length=len(_diario_pdf()))
    assert result.safe_result() == {
        "available": True,
        "delivery": "redirect",
        "format": "pdf",
        "content_length": len(_diario_pdf()),
    }
    assert "private" not in repr(result)


def test_diario_probe_submits_a_bounded_official_post_form() -> None:
    launch = b"""
      <form method="POST" action="https://sistemas.ufmg.br/diario/JasperServlet">
        <input type="hidden" name="course" value="safe-id">
      </form>
    """
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(launch, "https://virtual.ufmg.br/20262/mod/url/view.php?id=99"),
            _Response(
                _diario_pdf(),
                "https://sistemas.ufmg.br/diario/JasperServlet",
                content_type="application/pdf",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).probe_diario_plan(
        "token-safe", term="2026-2", source_id=99
    )

    assert result.delivery == "form"
    request = opener.requests[3][0]
    assert request.method == "POST"
    assert request.data == b"course=safe-id"
    assert request.headers["Origin"] == "https://virtual.ufmg.br"


@pytest.mark.parametrize(
    "markup",
    [
        '<a href="https://sistemas.ufmg.br/diario/JasperServlet?report=safe">Abrir</a>',
        '<iframe src="https://sistemas.ufmg.br/diario/JasperServlet?report=safe"></iframe>',
        '<embed src="https://sistemas.ufmg.br/diario/JasperServlet?report=safe">',
        '<object data="https://sistemas.ufmg.br/diario/JasperServlet?report=safe"></object>',
    ],
)
def test_diario_probe_follows_a_single_official_get_target(markup: str) -> None:
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                markup.encode(),
                "https://virtual.ufmg.br/20262/mod/url/view.php?id=99",
            ),
            _Response(
                _diario_pdf(),
                "https://sistemas.ufmg.br/diario/JasperServlet?report=safe",
                content_type="application/pdf",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).probe_diario_plan(
        "token-safe", term="2026-2", source_id=99
    )

    assert result.delivery == "link"
    request = opener.requests[3][0]
    assert request.get_method() == "GET"
    assert request.data is None


def test_diario_probe_follows_the_real_official_request_and_accepts_html() -> None:
    launch_url = (
        "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
        "solicitarRelatorioPlanoEnsino.do?"
        "plt=20262&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO"
    )
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                f'<a href="{launch_url}">Plano de Ensino</a>'.encode(),
                "https://virtual.ufmg.br/20262/mod/url/view.php?id=99",
            ),
            _Response(
                b'''<script>
                  const ignored='not-a-report';
                  window.location='/diario/JasperServlet';
                </script>''',
                launch_url,
                content_type="text/html; charset=utf-8",
            ),
            _Response(
                _diario_html(),
                "https://sistemas.ufmg.br/diario/JasperServlet",
                content_type="text/html; charset=utf-8",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).probe_diario_plan(
        "token-safe", term="2026-2", source_id=99
    )

    assert result == DiarioPlanProbe(
        delivery="link", content_length=len(_diario_html()), format="html"
    )
    launch_request = opener.requests[3][0]
    assert launch_request.full_url == launch_url
    assert launch_request.get_method() == "GET"
    report_request = opener.requests[4][0]
    assert report_request.full_url == "https://sistemas.ufmg.br/diario/JasperServlet"
    assert report_request.get_method() == "GET"


@pytest.mark.parametrize(
    "body,reason",
    [
        (b"\xff", "diario_transition_encoding"),
        (b"<html><body>sem destino</body></html>", "diario_transition_target"),
        (
            b'''<script>
              window.location='/diario/JasperServlet?first=1';
              const fallback='/diario/JasperServlet?second=1';
            </script>''',
            "diario_transition_targets",
        ),
    ],
)
def test_diario_transition_rejects_invalid_or_ambiguous_targets(
    body: bytes, reason: str
) -> None:
    source_url = (
        "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
        "solicitarRelatorioPlanoEnsino.do?"
        "plt=20262&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO"
    )

    with pytest.raises(InvalidMoodleResponse) as caught:
        _diario_transition_target(body, source_url)

    assert caught.value.reason == reason


@pytest.mark.parametrize(
    "url",
    [
        (
            "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?"
            "plt=20262&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO"
        ),
        "https://sistemas.ufmg.br/diario/JasperServlet",
    ],
)
def test_diario_launch_url_accepts_only_the_two_observed_official_targets(url: str) -> None:
    assert _is_diario_launch_url(url)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "x" * 8_193,
        (
            "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?plt=20262&oft=1000057&tac=DIG&aac=ELE631"
        ),
        (
            "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?"
            "plt=20262&plt=20261&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO"
        ),
        (
            "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?"
            "plt=20262&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO&next=https://attacker.example"
        ),
        (
            "https://sistemas.ufmg.br/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?plt"
        ),
        (
            "https://attacker.example/diario/planoAula/relatorio/solicitar/"
            "solicitarRelatorioPlanoEnsino.do?"
            "plt=20262&oft=1000057&tac=DIG&aac=ELE631&trm=TAPO"
        ),
    ],
)
def test_diario_launch_url_rejects_incomplete_ambiguous_or_external_targets(
    url: object,
) -> None:
    assert not _is_diario_launch_url(url)


@pytest.mark.parametrize(
    "url,content_type,body,exception,reason",
    [
        (
            "https://sistemas.ufmg.br/idp/login.jsp",
            "text/html",
            b"login",
            UFMGReauthenticationRequired,
            None,
        ),
        (
            "https://attacker.example/x",
            "text/html",
            _diario_html(),
            InvalidMoodleResponse,
            "diario_response_url",
        ),
        (
            "https://sistemas.ufmg.br/diario/JasperServlet",
            "application/json",
            b"{}",
            InvalidMoodleResponse,
            "diario_response_type",
        ),
        (
            "https://sistemas.ufmg.br/diario/JasperServlet",
            "text/html",
            b"\xff",
            InvalidMoodleResponse,
            "diario_response_encoding",
        ),
        (
            "https://sistemas.ufmg.br/diario/JasperServlet",
            "text/html",
            b"<html><body>not a plan</body></html>",
            InvalidMoodleResponse,
            "diario_response_html",
        ),
    ],
)
def test_diario_document_gate_classifies_rejected_html(
    url: str,
    content_type: str,
    body: bytes,
    exception: type[Exception],
    reason: str | None,
) -> None:
    with pytest.raises(exception) as caught:
        _require_diario_document(url, content_type, body)
    if reason is not None:
        assert isinstance(caught.value, InvalidMoodleResponse)
        assert caught.value.reason == reason


def test_diario_probe_rejects_a_non_utf8_launch_page() -> None:
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(b"\xff", "https://virtual.ufmg.br/20262/mod/url/view.php?id=99"),
        ]
    )
    with pytest.raises(InvalidMoodleResponse) as caught:
        MoodleStructuredDatesClient(opener=opener).probe_diario_plan(
            "token-safe", term="2026-2", source_id=99
        )
    assert caught.value.reason == "diario_launch_encoding"


@pytest.mark.parametrize(
    "markup,reason",
    [
        ("<p>none</p>", "diario_launch_target"),
        (
            '<form method="post" action="https://sistemas.ufmg.br/diario/JasperServlet"></form>',
            "diario_launch_form",
        ),
        (
            """<form method="post" action="https://sistemas.ufmg.br/diario/JasperServlet">
            <input name="a" value="1"></form>
            <form method="post" action="https://sistemas.ufmg.br/diario/JasperServlet">""",
            "diario_launch_forms",
        ),
        (
            """<form method="post" action="https://sistemas.ufmg.br/diario/JasperServlet">
            <input name="bad name" value="1"></form>""",
            "diario_launch_field",
        ),
        (
            """<form method="post" action="https://sistemas.ufmg.br/diario/JasperServlet">
            <input name="a" value="1"><input name="a" value="2"></form>""",
            "diario_launch_field",
        ),
        (
            """<a href="https://sistemas.ufmg.br/diario/JasperServlet?a=1">one</a>
            <iframe src="https://sistemas.ufmg.br/diario/JasperServlet?a=2"></iframe>""",
            "diario_launch_targets",
        ),
    ],
)
def test_diario_form_parser_rejects_ambiguous_or_unbounded_forms(
    markup: str, reason: str
) -> None:
    parser = _DiarioFormParser()
    with pytest.raises(InvalidMoodleResponse) as caught:
        parser.feed(markup)
        parser.result()
    assert caught.value.reason == reason


def test_diario_form_parser_ignores_untrusted_and_non_post_forms() -> None:
    parser = _DiarioFormParser()
    parser.feed(
        '<form method="get" action="https://sistemas.ufmg.br/diario/JasperServlet">'
        '<input name="ignored" value="1"></form>'
        '<a href="https://attacker.example/diario/JasperServlet">ignored</a>'
        '<form method="post" action="https://attacker.example/x"></form>'
    )
    with pytest.raises(InvalidMoodleResponse, match="invalid Moodle response"):
        parser.result()


@pytest.mark.parametrize(
    "url,content_type,body,exception,reason",
    [
        (
            "https://sistemas.ufmg.br/idp/login.jsp",
            "text/html",
            b"login",
            UFMGReauthenticationRequired,
            None,
        ),
        (
            "https://attacker.example/x",
            "application/pdf",
            b"%PDF-1.7%%EOF",
            InvalidMoodleResponse,
            "diario_response_url",
        ),
        (
            "https://sistemas.ufmg.br/diario/JasperServlet",
            "text/html",
            b"html",
            InvalidMoodleResponse,
            "diario_response_type",
        ),
        (
            "https://sistemas.ufmg.br/diario/JasperServlet",
            "application/pdf",
            b"not-pdf",
            InvalidMoodleResponse,
            "diario_response_pdf",
        ),
    ],
)
def test_diario_pdf_gate_classifies_every_rejected_response(
    url: str,
    content_type: str,
    body: bytes,
    exception: type[Exception],
    reason: str | None,
) -> None:
    with pytest.raises(exception) as caught:
        _require_diario_pdf(url, content_type, body)
    if reason is not None:
        assert isinstance(caught.value, InvalidMoodleResponse)
        assert caught.value.reason == reason


def test_diario_url_and_moodle_module_guards_reject_unsafe_shapes() -> None:
    assert _is_diario_url(None) is False
    assert _is_diario_url("x" * 8_193) is False
    assert _is_diario_url("https://user@sistemas.ufmg.br/diario/JasperServlet") is False
    assert _is_diario_url("https://sistemas.ufmg.br/diario/JasperServlet#x") is False
    assert _is_moodle_module(
        "https://virtual.ufmg.br/20262/mod/url/view.php?id=1",
        "/20262/mod/url/view.php",
    )
    assert not _is_moodle_module(
        "https://virtual.ufmg.br:444/20262/mod/url/view.php?id=1",
        "/20262/mod/url/view.php",
    )


@pytest.mark.parametrize("source_id", [0, True, 2_147_483_648])
def test_diario_probe_rejects_invalid_source_ids(source_id: object) -> None:
    with pytest.raises(ValueError, match="invalid Diario source"):
        MoodleStructuredDatesClient(opener=_Opener([])).probe_diario_plan(
            "token-safe", term="2026-2", source_id=source_id  # type: ignore[arg-type]
        )


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


def _mobile_callback(root: str, passport: str, *, private_token: str = "aaaaaaaaaaaaaaaa") -> str:
    site_id = md5(f"https://virtual.ufmg.br{root}{passport}".encode()).hexdigest()
    payload = f"{site_id}:::bbbbbbbbbbbbbbbb:::{private_token}".encode()
    return f"moodlemobile://token={b64encode(payload).decode()}"


def test_mobile_capability_probe_returns_only_non_secret_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passport = "a" * 32
    callback = _mobile_callback("/20262", passport)
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(b"", callback),
            _Response(
                json.dumps(
                    {
                        "downloadfiles": 1,
                        "userprivateaccesskey": "cccccccccccccccc",
                    }
                ).encode(),
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            ),
        ]
    )
    monkeypatch.setattr(module, "token_hex", lambda _length: passport)

    authorization = MoodleStructuredDatesClient(opener=opener).authorize_mobile_download(
        "token-safe",
        term="2026-2",
    )

    assert authorization == MoodleMobileAuthorization(
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        direct_download_supported=True,
        download_files=True,
        private_file_access=True,
    )
    assert authorization.safe_capabilities() == {
        "direct_download_supported": True,
        "download_files": True,
        "private_file_access": True,
        "webservice_token_issued": True,
    }
    assert "bbbbbbbbbbbbbbbb" not in repr(authorization.safe_capabilities())
    launch_request = opener.requests[2][0]
    assert launch_request.full_url.startswith(
        "https://virtual.ufmg.br/20262/admin/tool/mobile/launch.php?"
    )
    site_info_request = opener.requests[3][0]
    assert site_info_request.full_url == (
        "https://virtual.ufmg.br/20262/webservice/rest/server.php"
    )
    assert b"core_webservice_get_site_info" in site_info_request.data
    assert b"moodlewssettingfileurl=1" in site_info_request.data


@pytest.mark.parametrize(
    ("callback", "reason"),
    [
        ("https://attacker.example/token=value", "mobile_callback_origin"),
        ("moodlemobile://token=not-base64!", "mobile_callback_encoding"),
        (
            "moodlemobile://token=" + b64encode(b"wrong:::bbbbbbbbbbbbbbbb").decode(),
            "mobile_callback_site",
        ),
    ],
)
def test_mobile_capability_probe_rejects_untrusted_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    callback: str,
    reason: str,
) -> None:
    monkeypatch.setattr(module, "token_hex", lambda _length: "a" * 32)
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(b"", callback),
        ]
    )

    with pytest.raises(InvalidMoodleResponse) as captured:
        MoodleStructuredDatesClient(opener=opener).authorize_mobile_download(
            "token-safe",
            term="2026-2",
        )

    assert captured.value.reason == reason


def test_mobile_capability_probe_accepts_redirect_and_reports_missing_private_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passport = "b" * 32
    callback = _mobile_callback("/20262", passport, private_token="")
    callback = "moodlemobile://token=" + b64encode(
        b64decode(callback.removeprefix("moodlemobile://token=")).rsplit(b":::", 1)[0]
    ).decode()
    headers = Message()
    headers["Location"] = callback
    redirect = HTTPError("https://virtual.ufmg.br/20262/launch", 303, "redirect", headers, None)
    opener = _Opener(
        [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            redirect,
            _Response(
                b'{"downloadfiles":0,"userprivateaccesskey":""}',
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            ),
        ]
    )
    monkeypatch.setattr(module, "token_hex", lambda _length: passport)

    result = MoodleStructuredDatesClient(opener=opener).authorize_mobile_download(
        "token-safe",
        term="2026-2",
    )

    assert result.direct_download_supported is False
    assert result.download_files is False
    assert result.private_file_access is False


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (OSError("offline"), None),
        (HTTPError("https://virtual.ufmg.br", 500, "failure", Message(), None), None),
        (
            _Response(
                b"not json",
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            ),
            "site_info_json",
        ),
        (
            _Response(
                b'{"exception":"denied"}',
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            ),
            "site_info_rejected",
        ),
        (
            _Response(
                b"[]",
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            ),
            "site_info_rejected",
        ),
    ],
)
def test_mobile_capability_probe_maps_launch_and_site_info_failures(
    monkeypatch: pytest.MonkeyPatch,
    response: _Response | OSError,
    reason: str | None,
) -> None:
    passport = "c" * 32
    callback = _mobile_callback("/20262", passport)
    responses: list[_Response | OSError] = [
        _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
        _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
    ]
    if isinstance(response, HTTPError) or reason is None:
        responses.append(response)
    else:
        responses.extend([_Response(b"", callback), response])
    monkeypatch.setattr(module, "token_hex", lambda _length: passport)

    expected = MoodleUnavailable if reason is None else InvalidMoodleResponse
    with pytest.raises(expected) as captured:
        MoodleStructuredDatesClient(opener=_Opener(responses)).authorize_mobile_download(
            "token-safe",
            term="2026-2",
        )

    if reason is not None:
        assert captured.value.reason == reason


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"too:::many:::token1234567890:::parts", "mobile_callback_shape"),
        (b"SITE:::short", "mobile_callback_site"),
    ],
)
def test_mobile_token_payload_rejects_invalid_shape_or_site(payload: bytes, reason: str) -> None:
    callback = "moodlemobile://token=" + b64encode(payload).decode()
    with pytest.raises(InvalidMoodleResponse) as captured:
        _mobile_tokens(callback, "/20262", "passport")
    assert captured.value.reason == reason


def test_mobile_token_payload_rejects_invalid_tokens() -> None:
    passport = "passport"
    site_id = md5(f"https://virtual.ufmg.br/20262{passport}".encode()).hexdigest()
    with pytest.raises(InvalidMoodleResponse) as webservice_error:
        _mobile_tokens(
            "moodlemobile://token=" + b64encode(f"{site_id}:::short".encode()).decode(),
            "/20262",
            passport,
        )
    assert webservice_error.value.reason == "mobile_webservice_token"

    with pytest.raises(InvalidMoodleResponse) as private_error:
        _mobile_tokens(
            "moodlemobile://token="
            + b64encode(f"{site_id}:::bbbbbbbbbbbbbbbb:::short".encode()).decode(),
            "/20262",
            passport,
        )
    assert private_error.value.reason == "mobile_private_token"


def test_lists_module_files_with_private_file_urls_without_exposing_ws_token() -> None:
    response = [
        {
            "id": 44,
            "modules": [
                {
                    "id": 701,
                    "modname": "resource",
                    "contents": [
                        {
                            "type": "file",
                            "filename": "Plano de ensino.pdf",
                            "fileurl": (
                                "https://virtual.ufmg.br/20262/webservice/pluginfile.php/"
                                "700/mod_resource/content/1/plano.pdf?forcedownload=1&token=unsafe"
                            ),
                            "filesize": 12345,
                            "mimetype": "application/pdf",
                        }
                    ],
                }
            ],
        }
    ]
    opener = _Opener(
        [
            _Response(
                json.dumps(response).encode(),
                "https://virtual.ufmg.br/20262/webservice/rest/server.php",
                content_type="application/json",
            )
        ]
    )

    files = MoodleStructuredDatesClient(opener=opener).list_module_files(
        webservice_token="bbbbbbbbbbbbbbbb",
        private_token="aaaaaaaaaaaaaaaa",
        term="2026-2",
        course_id=3701,
        source_id=701,
    )

    assert files == [
        {
            "name": "Plano de ensino.pdf",
            "url": (
                "https://virtual.ufmg.br/20262/tokenpluginfile.php/"
                "aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf?forcedownload=1"
            ),
            "size": 12345,
            "mime_type": "application/pdf",
        }
    ]
    request = opener.requests[0][0]
    assert request.full_url == "https://virtual.ufmg.br/20262/webservice/rest/server.php"
    assert b"core_course_get_contents" in request.data
    assert b"courseid=3701" in request.data
    assert b"options%5B0%5D%5Bname%5D=cmid" in request.data
    assert b"options%5B0%5D%5Bvalue%5D=701" in request.data
    assert b"bbbbbbbbbbbbbbbb" in request.data
    assert "bbbbbbbbbbbbbbbb" not in repr(files)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"exception": "invalidtoken"}, "module_files_rejected"),
        ([], "module_not_found"),
        (
            [{"modules": [{"id": 701, "modname": "assign", "contents": []}]}],
            "module_kind",
        ),
        (
            [
                {
                    "modules": [
                        {
                            "id": 701,
                            "modname": "resource",
                            "contents": [
                                {
                                    "type": "file",
                                    "filename": "unsafe.pdf",
                                    "fileurl": "https://attacker.example/file.pdf",
                                    "filesize": 1,
                                    "mimetype": "application/pdf",
                                }
                            ],
                        }
                    ]
                }
            ],
            "module_file_url",
        ),
    ],
)
def test_module_files_reject_untrusted_or_unsupported_responses(
    payload: object,
    reason: str,
) -> None:
    with pytest.raises(InvalidMoodleResponse) as caught:
        _parse_module_files(
            json.dumps(payload).encode(),
            root="/20262",
            source_id=701,
            private_token="aaaaaaaaaaaaaaaa",
        )
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"not-json", "module_files_json"),
        (json.dumps({}).encode(), "module_files_shape"),
        (json.dumps([None]).encode(), "module_section_shape"),
        (json.dumps([{"modules": None}]).encode(), "module_list_shape"),
        (
            json.dumps(
                [
                    {
                        "modules": [
                            {"id": 701, "modname": "resource", "contents": []},
                            {"id": 701, "modname": "resource", "contents": []},
                        ]
                    }
                ]
            ).encode(),
            "module_conflict",
        ),
        (
            json.dumps(
                [{"modules": [{"id": 701, "modname": "resource", "contents": None}]}]
            ).encode(),
            "module_contents_shape",
        ),
        (
            json.dumps(
                [{"modules": [{"id": 701, "modname": "resource", "contents": [None]}]}]
            ).encode(),
            "module_file_shape",
        ),
        (
            json.dumps(
                [
                    {
                        "modules": [
                            {
                                "id": 701,
                                "modname": "resource",
                                "contents": [
                                    {
                                        "filename": " bad.pdf",
                                        "fileurl": (
                                            "https://virtual.ufmg.br/20262/pluginfile.php/"
                                            "1/mod_resource/content/1/bad.pdf"
                                        ),
                                    }
                                ],
                            }
                        ]
                    }
                ]
            ).encode(),
            "module_file_fields",
        ),
        (
            json.dumps(
                [
                    {
                        "modules": [
                            {
                                "id": 701,
                                "modname": "resource",
                                "contents": [
                                    {
                                        "filename": "A.pdf",
                                        "fileurl": (
                                            "https://virtual.ufmg.br/20262/pluginfile.php/"
                                            "1/mod_resource/content/1/same.pdf"
                                        ),
                                    },
                                    {
                                        "filename": "B.pdf",
                                        "fileurl": (
                                            "https://virtual.ufmg.br/20262/pluginfile.php/"
                                            "1/mod_resource/content/1/same.pdf"
                                        ),
                                    },
                                ],
                            }
                        ]
                    }
                ]
            ).encode(),
            "module_file_conflict",
        ),
    ],
)
def test_module_files_reject_malformed_shapes(payload: bytes, reason: str) -> None:
    with pytest.raises(InvalidMoodleResponse) as caught:
        _parse_module_files(
            payload,
            root="/20262",
            source_id=701,
            private_token="aaaaaaaaaaaaaaaa",
        )
    assert caught.value.reason == reason


def test_module_files_ignore_directories_and_accept_plain_pluginfile_urls() -> None:
    payload = json.dumps(
        [
            {
                "modules": [
                    {
                        "id": 701,
                        "modname": "folder",
                        "contents": [
                            {"type": "directory"},
                            {
                                "type": "file",
                                "filename": "Notas.txt",
                                "fileurl": (
                                    "https://virtual.ufmg.br/20262/pluginfile.php/"
                                    "1/mod_folder/content/1/notas.txt"
                                ),
                            },
                        ],
                    }
                ]
            }
        ]
    ).encode()
    files = _parse_module_files(
        payload,
        root="/20262",
        source_id=701,
        private_token="aaaaaaaaaaaaaaaa",
    )
    assert files[0]["size"] == 0
    assert files[0]["mime_type"] == "application/octet-stream"


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://virtual.ufmg.br/20262/pluginfile.php/a/b",
        "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_resource/content/../bad.pdf",
        "https://virtual.ufmg.br/20262/pluginfile.php/1/mod_resource/content/1/bad\\name.pdf",
    ],
)
def test_private_file_url_rejects_unsafe_paths(url: object) -> None:
    payload = [
        {
            "modules": [
                {
                    "id": 701,
                    "modname": "resource",
                    "contents": [{"filename": "File.pdf", "fileurl": url}],
                }
            ]
        }
    ]
    with pytest.raises(InvalidMoodleResponse) as caught:
        _parse_module_files(
            json.dumps(payload).encode(),
            root="/20262",
            source_id=701,
            private_token="aaaaaaaaaaaaaaaa",
        )
    assert caught.value.reason == "module_file_url"


@pytest.mark.parametrize(
    ("webservice_token", "private_token", "course_id", "source_id"),
    [
        ("short", "aaaaaaaaaaaaaaaa", 1, 1),
        ("bbbbbbbbbbbbbbbb", "short", 1, 1),
        ("bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", 0, 1),
        ("bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa", 1, 0),
    ],
)
def test_module_file_request_rejects_invalid_identifiers(
    webservice_token: str,
    private_token: str,
    course_id: int,
    source_id: int,
) -> None:
    with pytest.raises(ValueError):
        MoodleStructuredDatesClient(opener=_Opener([])).list_module_files(
            webservice_token=webservice_token,
            private_token=private_token,
            term="2026-2",
            course_id=course_id,
            source_id=source_id,
        )


@pytest.mark.parametrize(
    ("url", "content_type", "reason"),
    [
        (
            "https://attacker.example/20262/webservice/rest/server.php",
            "application/json",
            "site_info_redirect",
        ),
        (
            "https://virtual.ufmg.br/20262/webservice/rest/server.php",
            "text/html",
            "site_info_content_type",
        ),
    ],
)
def test_site_info_endpoint_is_strictly_allowlisted(
    url: str,
    content_type: str,
    reason: str,
) -> None:
    with pytest.raises(InvalidMoodleResponse) as captured:
        _require_json_endpoint(url, content_type, "/20262/webservice/rest/server.php")
    assert captured.value.reason == reason


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
            "moodle_course_id": "3701",
            "status": "found",
            "candidates": [
                {
                    "source_id": "101",
                    "kind": "page",
                    "title": "Plano de ensino",
                    "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                    "relevance": "teaching_plan",
                    "origin": "canonical",
                        "moodle_course_id": "3701",
                },
                {
                    "source_id": "102",
                    "kind": "file",
                    "title": "Cronograma da disciplina.pdf",
                    "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=102",
                    "relevance": "schedule",
                    "origin": "canonical",
                        "moodle_course_id": "3701",
                },
                {
                    "source_id": "103",
                    "kind": "text",
                    "title": "Orientações gerais",
                    "url": None,
                    "relevance": "other",
                    "origin": "canonical",
                        "moodle_course_id": "3701",
                },
            ],
        },
        {
            "course_code": "ELE028",
            "moodle_course_id": None,
            "status": "unmatched",
            "candidates": [],
        },
        {
            "course_code": "MAT001",
            "moodle_course_id": "4953",
            "status": "empty",
            "candidates": [],
        },
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
    ("course", "expected"),
    [
        (
            {"shortname": "MAT001   metaturma", "fullname": "Cálculo III"},
            True,
        ),
        (
            {"shortname": "MAT001", "fullname": "  Cálculo   METATURMA  "},
            True,
        ),
        (
            {"shortname": "MAT001", "fullname": "Laboratório de metaturmas"},
            False,
        ),
        (
            {"shortname": "MAT001", "fullname": "Curso comum"},
            False,
        ),
    ],
)
def test_metaturma_requires_an_isolated_word_after_space_normalization(
    course: dict[str, object], expected: bool
) -> None:
    assert _is_metaturma(course) is expected


def test_discovery_uses_single_canonical_course_and_keeps_metaturma_materials() -> None:
    courses = json.dumps(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        {
                            "id": 10,
                            "shortname": "MAT001",
                            "fullname": "Cálculo III",
                        },
                        {
                            "id": 11,
                            "shortname": "MAT001 metaturma A",
                            "fullname": "Cálculo III   METATURMA",
                        },
                        {
                            "id": 12,
                            "shortname": "MAT001 - METATURMA B",
                            "fullname": "Cálculo III",
                        },
                    ],
                    "nextoffset": 3,
                },
            }
        ]
    ).encode()
    states = json.dumps(
        [
            {
                "error": False,
                "data": json.dumps(
                    {
                        "course": {},
                        "section": [],
                        "cm": [
                            {
                                "id": 100,
                                "name": "Plano de ensino",
                                "module": "page",
                                "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=100",
                                "uservisible": True,
                            }
                        ],
                    }
                ),
            },
            {
                "error": False,
                "data": json.dumps(
                    {
                        "course": {},
                        "section": [],
                        "cm": [
                            {
                                "id": 101,
                                "name": "Lista da metaturma A",
                                "module": "resource",
                                "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=101",
                                "uservisible": True,
                            }
                        ],
                    }
                ),
            },
            {
                "error": False,
                "data": json.dumps(
                    {"course": {}, "section": [], "cm": []}
                ),
            },
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
                states,
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).discover(
        "token", term="2026-2", course_codes=["MAT001"]
    )

    assert result[0]["status"] == "found"
    assert [candidate["origin"] for candidate in result[0]["candidates"]] == [
        "canonical",
        "metaturma",
    ]
    assert [candidate["moodle_course_id"] for candidate in result[0]["candidates"]] == [
        "10",
        "11",
    ]
    state_calls = json.loads(opener.requests[3][0].data)
    assert [call["args"]["courseid"] for call in state_calls] == [10, 11, 12]


def test_discovery_keeps_multiple_non_metaturma_matches_ambiguous() -> None:
    courses = json.dumps(
        [
            {
                "error": False,
                "data": {
                    "courses": [
                        {"id": 1, "shortname": "MAT001 A", "fullname": "Cálculo A"},
                        {"id": 2, "shortname": "MAT001 B", "fullname": "Cálculo B"},
                        {
                            "id": 3,
                            "shortname": "MAT001 METATURMA",
                            "fullname": "Cálculo conjunto",
                        },
                    ],
                    "nextoffset": 3,
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
        ]
    )

    result = MoodleStructuredDatesClient(opener=opener).discover(
        "token", term="2026-2", course_codes=["MAT001"]
    )

    assert result == [
        {
            "course_code": "MAT001",
            "moodle_course_id": None,
            "status": "ambiguous",
            "candidates": [],
        }
    ]
    assert len(opener.requests) == 3


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
        {
            "id": 5,
            "name": "Plano de ensino",
            "module": "url",
            "url": "https://virtual.ufmg.br/20262/mod/url/view.php?id=5",
            "uservisible": True,
        },
    ]
    payload = json.dumps([{"error": False, "data": json.dumps({"cm": modules})}]).encode()
    result = _parse_course_states(payload, "/20262", 1)[0]
    assert [item["kind"] for item in result] == ["page", "file", "link"]
    assert result[0]["relevance"] == "teaching_plan"
    assert result[2]["relevance"] == "teaching_plan"


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
        7,
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
        (7, "course_module_url_type"),
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


@pytest.mark.parametrize("module", ["page", "book", "resource", "folder", "url"])
def test_candidate_url_builds_a_bounded_canonical_url_when_moodle_omits_it(
    module: str,
) -> None:
    assert _candidate_url(None, "/20262", module, 123) == (
        f"https://virtual.ufmg.br/20262/mod/{module}/view.php?id=123"
    )


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
