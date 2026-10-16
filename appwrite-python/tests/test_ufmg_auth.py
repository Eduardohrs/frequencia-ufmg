from http.cookiejar import Cookie, CookieJar
from io import BytesIO
from socket import gaierror
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs
from urllib.request import Request

import pytest

from ufmg_auth import (
    InvalidUFMGCredentials,
    UFMGAuthenticationUnavailable,
    UFMGAuthenticator,
    _default_opener,
    _HTTPSOnlyRedirectHandler,
)


class FakeResponse:
    def __init__(self, url: str, status: int = 200) -> None:
        self.url = url
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url


def _cookie(
    name: str,
    value: str,
    *,
    domain: str = "sistemas.ufmg.br",
    path: str = "/",
) -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=True,
        domain_initial_dot=False,
        path=path,
        path_specified=True,
        secure=True,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": ""},
        rfc2109=False,
    )


class FakeOpener:
    def __init__(self, jar: CookieJar, *, outcome: str = "success") -> None:
        self.jar = jar
        self.outcome = outcome
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        if self.outcome == "network-error":
            raise URLError("private network detail")
        if self.outcome == "portal-timeout":
            raise TimeoutError("private timeout detail")
        if self.outcome == "portal-dns":
            raise URLError(gaierror("private DNS detail"))
        if self.outcome == "credential-timeout" and len(self.requests) == 2:
            raise TimeoutError("private credential timeout detail")
        if len(self.requests) == 1:
            if self.outcome == "bad-initial":
                return FakeResponse("http://sistemas.ufmg.br/idp/login.jsp")
            if self.outcome != "missing-state":
                self.jar.set_cookie(_cookie("WASReqURL", "private-state"))
            return FakeResponse("https://sistemas.ufmg.br/portal/../idp/login.jsp")
        if self.outcome == "success":
            self.jar.set_cookie(
                _cookie(
                    "LtpaToken2",
                    "private-ltpa-token",
                    domain=".ufmg.br",
                    path="/portal",
                )
            )
            return FakeResponse("https://sistemas.ufmg.br/portal/revalidate.html")
        if self.outcome == "bad-token":
            self.jar.set_cookie(
                _cookie(
                    "LtpaToken2",
                    "external-cookie-must-not-be-used",
                    domain="attacker.example",
                )
            )
            self.jar.set_cookie(_cookie("LtpaToken2", "short"))
            return FakeResponse("https://sistemas.ufmg.br/portal/revalidate.html")
        if self.outcome == "foreign-redirect":
            return FakeResponse("https://attacker.example/portal/revalidate.html")
        return FakeResponse("https://sistemas.ufmg.br/idp/login.jsp")


def test_login_reproduces_the_required_two_step_flow_and_returns_only_ltpa_token() -> None:
    captured: list[FakeOpener] = []

    def factory(jar: CookieJar) -> FakeOpener:
        opener = FakeOpener(jar)
        captured.append(opener)
        return opener

    token = UFMGAuthenticator(opener_factory=factory, timeout_seconds=7).login(
        "2025019259", "private-sênha"
    )

    assert token == "private-ltpa-token"
    first, second = captured[0].requests
    assert first[0].full_url == "https://sistemas.ufmg.br/portal/render.userLayoutRootNode.uP"
    assert first[0].get_method() == "GET"
    assert second[0].full_url == "https://sistemas.ufmg.br/idp/j_security_check"
    assert second[0].get_method() == "POST"
    assert parse_qs(second[0].data.decode(), encoding="iso-8859-1") == {
        "j_username": ["2025019259"],
        "j_password": ["private-sênha"],
        "submit": ["Entrar"],
    }
    assert second[0].get_header("Origin") == "https://sistemas.ufmg.br"
    assert second[0].get_header("Referer") == ("https://sistemas.ufmg.br/portal/../idp/login.jsp")
    assert first[1] == second[1] == 7


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("bad-initial", "login_entry_rejected"),
        ("missing-state", "login_context_missing"),
        ("invalid-credentials", "credentials_rejected"),
        ("foreign-redirect", "login_response_rejected"),
        ("bad-token", "session_cookie_missing"),
    ],
)
def test_login_rejects_incomplete_or_untrusted_authentication(outcome: str, reason: str) -> None:
    captured: list[FakeOpener] = []

    def factory(jar: CookieJar) -> FakeOpener:
        opener = FakeOpener(jar, outcome=outcome)
        captured.append(opener)
        return opener

    with pytest.raises(InvalidUFMGCredentials) as caught:
        UFMGAuthenticator(opener_factory=factory).login("student", "private-password")

    assert "private-password" not in str(caught.value)
    assert "private-state" not in str(caught.value)
    assert "private-ltpa-token" not in str(caught.value)
    assert caught.value.reason == reason


def test_login_sanitizes_transport_failures() -> None:
    def factory(jar: CookieJar) -> FakeOpener:
        return FakeOpener(jar, outcome="network-error")

    with pytest.raises(UFMGAuthenticationUnavailable) as caught:
        UFMGAuthenticator(opener_factory=factory).login("student", "private-password")

    assert "private" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.reason == "portal_entry_network_error"


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("portal-timeout", "portal_entry_timeout"),
        ("portal-dns", "portal_entry_dns"),
        ("credential-timeout", "credential_submit_timeout"),
    ],
)
def test_login_exposes_only_bounded_transport_diagnostics(
    outcome: str, reason: str
) -> None:
    def factory(jar: CookieJar) -> FakeOpener:
        return FakeOpener(jar, outcome=outcome)

    with pytest.raises(UFMGAuthenticationUnavailable) as caught:
        UFMGAuthenticator(opener_factory=factory).login("student", "private-password")

    assert caught.value.reason == reason
    assert "private" not in str(caught.value)


def test_unavailable_reason_is_bounded() -> None:
    with pytest.raises(ValueError, match="invalid UFMG transport failure reason"):
        UFMGAuthenticationUnavailable("private-unbounded-detail")


def test_redirects_are_limited_to_https_on_the_institutional_host() -> None:
    handler = _HTTPSOnlyRedirectHandler()
    request = Request("https://sistemas.ufmg.br/idp/login.jsp")

    redirected = handler.redirect_request(
        request,
        BytesIO(),
        302,
        "Found",
        {},
        "https://sistemas.ufmg.br/portal/revalidate.html",
    )
    assert redirected is not None
    assert redirected.full_url == "https://sistemas.ufmg.br/portal/revalidate.html"

    with pytest.raises(URLError):
        handler.redirect_request(request, BytesIO(), 302, "Found", {}, "https://attacker.example/")


def test_default_opener_and_timeout_configuration_are_bounded() -> None:
    assert _default_opener(CookieJar()) is not None
    with pytest.raises(ValueError):
        UFMGAuthenticator(timeout_seconds=0)


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("", "valid-password"),
        ("student name", "valid-password"),
        ("x" * 51, "valid-password"),
        ("student", ""),
        ("student", "x" * 51),
        ("student", "line\nbreak"),
    ],
)
def test_login_rejects_invalid_input_before_any_network_call(username: str, password: str) -> None:
    called = False

    def factory(_jar: CookieJar) -> FakeOpener:
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(InvalidUFMGCredentials) as caught:
        UFMGAuthenticator(opener_factory=factory).login(username, password)

    assert called is False
    assert caught.value.reason == "input_rejected"


def test_invalid_failure_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        InvalidUFMGCredentials("private-or-unbounded-detail")
