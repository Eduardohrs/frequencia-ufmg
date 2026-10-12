"""Minimal server-side exchange from UFMG credentials to an LTPA session."""

from collections.abc import Callable
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    OpenerDirector,
    Request,
    build_opener,
)

_PORTAL_URL = "https://sistemas.ufmg.br/portal/render.userLayoutRootNode.uP"
_LOGIN_URL = "https://sistemas.ufmg.br/idp/j_security_check"
_SUCCESS_PATH = "/portal/revalidate.html"
_TRUSTED_HOST = "sistemas.ufmg.br"
_USERNAME_MAX_LENGTH = 64
_PASSWORD_MAX_LENGTH = 256
_TOKEN_MAX_LENGTH = 8_192


class InvalidUFMGCredentials(Exception):
    """Raised when credentials are invalid or the institutional flow is incomplete."""


class UFMGAuthenticationUnavailable(Exception):
    """Raised when the UFMG authentication service cannot be reached safely."""


class _HTTPSOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        target = urlsplit(new_url)
        if target.scheme != "https" or target.hostname != _TRUSTED_HOST:
            raise URLError("untrusted UFMG authentication redirect")
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def _default_opener(jar: CookieJar) -> OpenerDirector:
    return build_opener(HTTPCookieProcessor(jar), _HTTPSOnlyRedirectHandler())


class UFMGAuthenticator:
    """Perform the verified UFMG login sequence without retaining a password."""

    def __init__(
        self,
        *,
        opener_factory: Callable[[CookieJar], Any] = _default_opener,
        timeout_seconds: float = 10,
    ) -> None:
        if not 1 <= timeout_seconds <= 15:
            raise ValueError("invalid UFMG authentication timeout")
        self._opener_factory = opener_factory
        self._timeout_seconds = timeout_seconds

    def login(self, username: str, password: str) -> str:
        _validate_credentials(username, password)
        jar = CookieJar()
        opener = self._opener_factory(jar)
        try:
            with opener.open(
                Request(_PORTAL_URL, headers=_request_headers()),
                timeout=self._timeout_seconds,
            ) as response:
                if not _trusted_response(response.geturl(), "/idp/login.jsp"):
                    raise InvalidUFMGCredentials("UFMG authentication failed")
            if _cookie_value(jar, "WASReqURL") is None:
                raise InvalidUFMGCredentials("UFMG authentication failed")

            body = urlencode(
                {"j_username": username, "j_password": password}
            ).encode("utf-8")
            with opener.open(
                Request(
                    _LOGIN_URL,
                    data=body,
                    headers={
                        **_request_headers(),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    method="POST",
                ),
                timeout=self._timeout_seconds,
            ) as response:
                if not _trusted_response(response.geturl(), _SUCCESS_PATH):
                    raise InvalidUFMGCredentials("UFMG authentication failed")
        except InvalidUFMGCredentials:
            raise
        except OSError:
            raise UFMGAuthenticationUnavailable(
                "UFMG authentication unavailable"
            ) from None

        token = _cookie_value(jar, "LtpaToken2")
        if (
            token is None
            or not 8 <= len(token) <= _TOKEN_MAX_LENGTH
            or any(character.isspace() for character in token)
        ):
            raise InvalidUFMGCredentials("UFMG authentication failed")
        return token


def _validate_credentials(username: object, password: object) -> None:
    if (
        not isinstance(username, str)
        or not 1 <= len(username) <= _USERNAME_MAX_LENGTH
        or any(character.isspace() for character in username)
        or not isinstance(password, str)
        or not 1 <= len(password) <= _PASSWORD_MAX_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in password)
    ):
        raise InvalidUFMGCredentials("UFMG authentication failed")


def _request_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "Frequencia-UFMG/1.0",
    }


def _trusted_response(url: str, expected_path: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == _TRUSTED_HOST
        and parsed.path == expected_path
    )


def _cookie_value(jar: CookieJar, name: str) -> str | None:
    for cookie in jar:
        if cookie.name == name and cookie.domain == _TRUSTED_HOST and cookie.path == "/":
            return cookie.value
    return None
