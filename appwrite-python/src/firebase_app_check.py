"""Verify Firebase App Check tokens for the custom Python backend."""

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

from google.auth import jwt
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_token

APP_CHECK_JWKS_URL = "https://firebaseappcheck.googleapis.com/v1/jwks"
MAX_TOKEN_LENGTH = 16_384
VERIFICATION_TIMEOUT_SECONDS = 5
TokenVerifier = Callable[[str, str], Mapping[str, Any]]


class InvalidAppCheck(Exception):
    """A request did not contain a valid token from an allowlisted app."""

    _safe_reasons = frozenset({"claims", "configuration", "header", "token", "verification"})

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in self._safe_reasons else "verification"
        super().__init__("invalid App Check")


@dataclass(frozen=True, slots=True)
class FirebaseAppIdentity:
    """The minimum verified App Check data needed by the request guard."""

    app_id: str
    expires_at: int
    token_digest: str


def verify_firebase_app_check(
    headers: Mapping[str, str],
    *,
    project_number: str,
    allowed_app_ids: Set[str],
    now: int,
    verify_token: TokenVerifier | None = None,
) -> FirebaseAppIdentity:
    """Validate signature, JWT metadata, project, expiry and app allowlist."""

    token = _app_check_token(headers)
    if not project_number.isdigit() or not allowed_app_ids:
        raise InvalidAppCheck("configuration")

    audience = f"projects/{project_number}"
    try:
        decode_header = cast(Any, jwt.decode_header)
        header = decode_header(token)
    except Exception:
        raise InvalidAppCheck("header") from None
    try:
        claims = (verify_token or _verify_google_token)(token, audience)
    except Exception:
        raise InvalidAppCheck("verification") from None

    claim_audience = claims.get("aud")
    audiences = {claim_audience} if isinstance(claim_audience, str) else set(claim_audience or [])
    app_id = claims.get("sub")
    expires_at = claims.get("exp")
    issued_at = claims.get("iat")
    if (
        header.get("alg") != "RS256"
        or header.get("typ") != "JWT"
        or audience not in audiences
        or claims.get("iss")
        != f"https://firebaseappcheck.googleapis.com/{project_number}"
        or not isinstance(app_id, str)
        or app_id not in allowed_app_ids
        or not isinstance(expires_at, int)
        or expires_at <= now
        or not isinstance(issued_at, int)
        or issued_at > now
    ):
        raise InvalidAppCheck("claims")

    return FirebaseAppIdentity(
        app_id=app_id,
        expires_at=expires_at,
        token_digest=sha256(token.encode()).hexdigest(),
    )


def _app_check_token(headers: Mapping[str, str]) -> str:
    token = next(
        (value for key, value in headers.items() if key.lower() == "x-firebase-appcheck"),
        "",
    )
    if (
        not token
        or len(token) > MAX_TOKEN_LENGTH
        or token.count(".") != 2
        or any(character.isspace() for character in token)
    ):
        raise InvalidAppCheck("token")
    return token


def _verify_google_token(token: str, audience: str) -> Mapping[str, Any]:
    request = Request()

    def bounded_request(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", VERIFICATION_TIMEOUT_SECONDS)
        return request(*args, **kwargs)

    untyped_verify = cast(Any, verify_token)
    claims = untyped_verify(
        token,
        bounded_request,
        audience=audience,
        certs_url=APP_CHECK_JWKS_URL,
    )
    if not isinstance(claims, Mapping):
        raise ValueError("invalid App Check claims")
    return cast(Mapping[str, Any], claims)
