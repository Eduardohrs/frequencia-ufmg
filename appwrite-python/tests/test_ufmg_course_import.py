import json
import ssl
from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import ufmg_course_import as import_module
from ufmg_course_import import (
    InvalidUFMGEnrollmentResponse,
    UFMGCourseImportService,
    UFMGEnrollmentClient,
    UFMGEnrollmentUnavailable,
    _HTTPSOnlyRedirectHandler,
)
from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


def _payload() -> dict[str, object]:
    return {
        "listaObj": [
            {
                "semestreLetivo": "2026/2",
                "dataInicialSemestre": "01/07/2026",
                "dataFinalSemestre": "31/12/2026",
                "matriculas": [
                    {
                        "turma": {
                            "atividadeAcademica": {
                                "codigo": " ele028 ",
                                "nomeReduzido": "Laboratório de Circuitos",
                                "cargaHoraria": 30,
                            },
                            "horarios": [{"diaDaSemana": "SEGUNDA"}],
                        }
                    },
                    {
                        "turma": {
                            "atividadeAcademica": {
                                "codigo": "LA631",
                                "nome": "Língua Alemã I",
                                "cargaHoraria": "60",
                            }
                        }
                    },
                ],
            }
        ]
    }


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas",
        content_type: str = "application/json;charset=ISO-8859-1",
    ) -> None:
        self._body = body
        self._url = url
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        assert limit == 262_145
        return self._body

    def geturl(self) -> str:
        return self._url


def test_client_reads_only_enrollment_fields_and_never_exposes_the_token() -> None:
    calls: list[tuple[Any, float]] = []

    def open_response(request: Any, *, timeout: float) -> _Response:
        calls.append((request, timeout))
        return _Response(json.dumps(_payload(), ensure_ascii=False).encode("iso-8859-1"))

    courses = UFMGEnrollmentClient(open_response=open_response, timeout_seconds=7).fetch(
        "private-ltpa-token"
    )

    assert courses == [
        {
            "code": "ELE028",
            "name": "Laboratório de Circuitos",
            "term": "2026-2",
            "workload": 30,
        },
        {"code": "LA631", "name": "Língua Alemã I", "term": "2026-2", "workload": 60},
    ]
    request, timeout = calls[0]
    assert request.full_url.endswith("/WsMatriculas")
    assert request.get_header("Cookie") == "LtpaToken2=private-ltpa-token"
    assert request.get_header("Accept") is None
    assert request.get_header("User-agent") is None
    assert timeout == 7
    assert "private-ltpa-token" not in repr(courses)

    numeric_term = _payload()
    numeric_term["listaObj"][0]["semestreLetivo"] = 20262  # type: ignore[index]
    numeric_client = UFMGEnrollmentClient(
        open_response=lambda *_args, **_kwargs: _Response(
            json.dumps(numeric_term, ensure_ascii=False).encode("iso-8859-1")
        )
    )
    assert {course["term"] for course in numeric_client.fetch("private-token")} == {
        "2026-2"
    }


@pytest.mark.parametrize(
    "response",
    [
        _Response(
            b"<html>login</html>",
            url="https://sistemas.ufmg.br/idp/login.jsp",
            content_type="text/html",
        ),
        _Response(b"{}"),
        _Response(b"x"),
        _Response(b'{"listaObj":[{"semestreLetivo":"2026/2","matriculas":[{}]}]}'),
        _Response(b"x" * 262_145),
    ],
)
def test_client_rejects_login_redirects_malformed_and_oversized_responses(
    response: _Response,
) -> None:
    client = UFMGEnrollmentClient(open_response=lambda *_args, **_kwargs: response)

    with pytest.raises((InvalidUFMGEnrollmentResponse, UFMGReauthenticationRequired)):
        client.fetch("private-ltpa-token")


@pytest.mark.parametrize(
    "response",
    [
        _Response(b"{}", url="http://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas"),
        _Response(b"{}", url="https://attacker.example/siga-ws/seam/resource/rest/WsMatriculas"),
        _Response(b"{}", url="https://sistemas.ufmg.br/other"),
    ],
)
def test_client_requires_the_exact_trusted_endpoint(response: _Response) -> None:
    with pytest.raises(UFMGReauthenticationRequired):
        UFMGEnrollmentClient(open_response=lambda *_args, **_kwargs: response).fetch(
            "private-token"
        )


def test_client_accepts_valid_bounded_json_from_the_legacy_plain_text_endpoint() -> None:
    response = _Response(
        json.dumps(_payload(), ensure_ascii=False).encode("iso-8859-1"),
        content_type="text/plain;charset=ISO-8859-1",
    )

    courses = UFMGEnrollmentClient(
        open_response=lambda *_args, **_kwargs: response
    ).fetch("private-token")

    assert [course["code"] for course in courses] == ["ELE028", "LA631"]


@pytest.mark.parametrize(
    "payload",
    [
        {"listaObj": []},
        {"listaObj": [None]},
        {"listaObj": [{"semestreLetivo": "2026/2", "matriculas": None}]},
        {"listaObj": [{"semestreLetivo": "bad", "matriculas": []}]},
        {
            "listaObj": [
                {
                    "semestreLetivo": "2026/2",
                    "matriculas": [
                        {
                            "turma": {
                                "atividadeAcademica": {
                                    "codigo": "bad code",
                                    "nomeReduzido": "Nome",
                                    "cargaHoraria": 60,
                                }
                            }
                        }
                    ],
                }
            ]
        },
    ],
)
def test_client_rejects_each_malformed_enrollment_boundary(payload: object) -> None:
    response = _Response(json.dumps(payload).encode())
    with pytest.raises(InvalidUFMGEnrollmentResponse):
        UFMGEnrollmentClient(open_response=lambda *_args, **_kwargs: response).fetch(
            "private-token"
        )


def test_client_rejects_unbounded_timeout_configuration() -> None:
    with pytest.raises(ValueError):
        UFMGEnrollmentClient(timeout_seconds=0)


def test_enrollment_redirects_cannot_leak_the_session_to_another_host() -> None:
    handler = _HTTPSOnlyRedirectHandler()
    request = Request("https://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas")

    assert handler.redirect_request(
        request,
        BytesIO(),
        302,
        "Found",
        {},
        "https://sistemas.ufmg.br/idp/login.jsp",
    ) is not None
    with pytest.raises(URLError):
        handler.redirect_request(
            request,
            BytesIO(),
            302,
            "Found",
            {},
            "https://attacker.example/steal",
        )


def test_default_transport_uses_the_hardened_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, float]] = []

    class Opener:
        def open(self, request: object, *, timeout: float) -> str:
            calls.append((request, timeout))
            return "response"

    monkeypatch.setattr(import_module, "build_opener", lambda _handler: Opener())
    request = Request("https://sistemas.ufmg.br/siga-ws/seam/resource/rest/WsMatriculas")

    assert import_module._open_response(request, timeout=7) == "response"
    assert calls == [(request, 7)]


@pytest.mark.parametrize(
    "activity",
    [
        {"codigo": 123, "nomeReduzido": "Nome", "cargaHoraria": 60},
        {"codigo": "ELE028", "cargaHoraria": 60},
        {"codigo": "ELE028", "nomeReduzido": "Nome", "cargaHoraria": True},
        {"codigo": "ELE028", "nomeReduzido": "Nome", "cargaHoraria": 30.5},
    ],
)
def test_client_rejects_ambiguous_academic_field_types(
    activity: dict[str, object],
) -> None:
    payload = {
        "listaObj": [
            {
                "semestreLetivo": "2026/2",
                "matriculas": [{"turma": {"atividadeAcademica": activity}}],
            }
        ],
        "futureMetadata": "is safely ignored",
    }
    response = _Response(json.dumps(payload).encode())

    with pytest.raises(InvalidUFMGEnrollmentResponse):
        UFMGEnrollmentClient(open_response=lambda *_args, **_kwargs: response).fetch(
            "private-token"
        )


def test_client_sanitizes_network_failures() -> None:
    def fail(*_args: Any, **_kwargs: Any) -> BytesIO:
        raise URLError("private network detail")

    with pytest.raises(UFMGEnrollmentUnavailable) as caught:
        UFMGEnrollmentClient(open_response=fail).fetch("private-ltpa-token")

    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    ("failure", "reason", "upstream_status"),
    [
        (
            HTTPError(
                "https://sistemas.ufmg.br/redacted",
                503,
                "private upstream detail",
                {},
                None,
            ),
            "http_error",
            503,
        ),
        (TimeoutError("private timeout detail"), "timeout", None),
        (URLError(TimeoutError("private timeout detail")), "timeout", None),
        (URLError(ssl.SSLError("private TLS detail")), "tls", None),
        (URLError("private network detail"), "network", None),
    ],
)
def test_client_classifies_transport_failures_without_leaking_details(
    failure: OSError,
    reason: str,
    upstream_status: int | None,
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> BytesIO:
        raise failure

    with pytest.raises(UFMGEnrollmentUnavailable) as caught:
        UFMGEnrollmentClient(open_response=fail).fetch("private-ltpa-token")

    assert caught.value.reason == reason
    assert caught.value.upstream_status == upstream_status
    assert "private" not in str(caught.value)


class _Store:
    def __init__(self, session: UFMGSession | None) -> None:
        self.session = session

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        assert user_id == "firebase-user"
        assert now == 1_760_000_000
        return self.session

    def delete(self, user_id: str) -> None:
        assert user_id == "firebase-user"
        self.session = None


class _Client:
    def fetch(self, token: str) -> list[dict[str, object]]:
        assert token == "private-token"
        return [
            {"code": "ELE028", "name": "Circuitos", "term": "2026-2", "workload": 30},
            {"code": "LA631", "name": "Alemão", "term": "2026-2", "workload": 60},
            {"code": "LA631", "name": "Alemão", "term": "2026-2", "workload": 60},
        ]


class _Courses:
    def __init__(self) -> None:
        self.saved: list[dict[str, object]] = []

    def list_courses(self) -> list[dict[str, object]]:
        return [{"id": "manual", "code": "ELE028", "name": "Nome manual"}]

    def save_course(self, payload: dict[str, object]) -> dict[str, object]:
        self.saved.append(payload)
        return payload


def test_import_creates_only_missing_courses_and_preserves_existing_data() -> None:
    courses = _Courses()
    service = UFMGCourseImportService(
        _Store(UFMGSession("private-token", 1_759_990_000, 1_760_022_400)),
        _Client(),
        courses,
        clock=lambda: datetime(2026, 10, 12, 12, tzinfo=UTC),
    )

    result = service.import_courses("firebase-user", now=1_760_000_000)

    assert result == {"created": 1, "existing": 1, "total": 2}
    assert courses.saved == [
        {
            "id": "ufmg-2026-2-la631",
            "code": "LA631",
            "name": "Alemão",
            "workload": 60,
            "term": "2026-2",
            "starts_on": None,
            "ends_on": None,
            "created_at": "2026-10-12T12:00:00Z",
            "updated_at": "2026-10-12T12:00:00Z",
        }
    ]


def test_import_requires_a_live_saved_session() -> None:
    service = UFMGCourseImportService(_Store(None), _Client(), _Courses())

    with pytest.raises(UFMGReauthenticationRequired):
        service.import_courses("firebase-user", now=1_760_000_000)


def test_import_removes_a_rejected_remote_session() -> None:
    store = _Store(UFMGSession("private-token", 1_759_990_000, 1_760_022_400))

    class ExpiredClient:
        def fetch(self, _token: str) -> list[dict[str, object]]:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")

    service = UFMGCourseImportService(store, ExpiredClient(), _Courses())

    with pytest.raises(UFMGReauthenticationRequired):
        service.import_courses("firebase-user", now=1_760_000_000)

    assert store.session is None
