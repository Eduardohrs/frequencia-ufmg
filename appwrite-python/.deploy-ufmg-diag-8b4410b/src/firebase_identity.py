"""Verify Firebase ID tokens without granting Appwrite administrative access."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_firebase_token

MAX_TOKEN_LENGTH = 16_384
TokenVerifier = Callable[[str, str], Mapping[str, Any]]


class InvalidIdentity(Exception):
    """A caller did not provide a valid identity for this Firebase project."""


@dataclass(frozen=True, slots=True)
class FirebaseIdentity:
    """The minimum verified identity needed to enforce per-user ownership."""

    uid: str


def verify_firebase_identity(
    headers: Mapping[str, str],
    project_id: str,
    verify_token: TokenVerifier | None = None,
) -> FirebaseIdentity:
    """Validate a bearer token and return only its stable Firebase user ID."""

    token = firebase_bearer_token(headers)
    if not project_id:
        raise InvalidIdentity("invalid Firebase identity")

    try:
        claims = (verify_token or _verify_google_token)(token, project_id)
    except Exception:
        raise InvalidIdentity("invalid Firebase identity") from None

    expected_issuer = f"https://securetoken.google.com/{project_id}"
    uid = claims.get("sub")
    if (
        claims.get("aud") != project_id
        or claims.get("iss") != expected_issuer
        or not isinstance(uid, str)
        or not uid
        or len(uid) > 128
    ):
        raise InvalidIdentity("invalid Firebase identity")
    return FirebaseIdentity(uid=uid)


def firebase_bearer_token(headers: Mapping[str, str]) -> str:
    """Return a strictly validated bearer token without logging or persisting it."""
    authorization = next(
        (value for key, value in headers.items() if key.lower() == "authorization"),
        "",
    )
    parts = authorization.split()
    if (
        len(parts) != 2
        or parts[0].lower() != "bearer"
        or not parts[1]
        or len(parts[1]) > MAX_TOKEN_LENGTH
    ):
        raise InvalidIdentity("invalid Firebase identity")
    return parts[1]


def _verify_google_token(token: str, project_id: str) -> Mapping[str, Any]:
    untyped_verify = cast(Any, verify_firebase_token)
    claims = untyped_verify(token, Request(), audience=project_id)
    if not isinstance(claims, Mapping):
        raise ValueError("invalid token claims")
    return cast(Mapping[str, Any], claims)
