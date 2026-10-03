import base64
import json
from collections.abc import Mapping
from typing import Any

import pytest

import firebase_app_check as app_check_module
from firebase_app_check import (
    FirebaseAppIdentity,
    InvalidAppCheck,
    verify_firebase_app_check,
)


def _token(header: Mapping[str, Any] | None = None) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(header or {"alg": "RS256", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(b"{}").decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"signature").decode().rstrip("=")
    return f"{encoded}.{payload}.{signature}"


def test_verify_app_check_accepts_expected_project_and_registered_app() -> None:
    token = _token()

    def verify_token(value: str, audience: str) -> Mapping[str, Any]:
        assert value == token
        assert audience == "projects/123456789"
        return {
            "aud": [audience],
            "exp": 2_000,
            "iat": 1_000,
            "iss": "https://firebaseappcheck.googleapis.com/123456789",
            "sub": "1:123456789:web:registered",
        }

    identity = verify_firebase_app_check(
        {"X-Firebase-AppCheck": token},
        project_number="123456789",
        allowed_app_ids={"1:123456789:web:registered"},
        now=1_500,
        verify_token=verify_token,
    )

    assert identity == FirebaseAppIdentity(
        app_id="1:123456789:web:registered",
        expires_at=2_000,
        token_digest=app_check_module.sha256(token.encode()).hexdigest(),
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-firebase-appcheck": ""},
        {"x-firebase-appcheck": "three parts are required"},
        {"x-firebase-appcheck": "x" * 16_385},
    ],
)
def test_verify_app_check_rejects_missing_or_malformed_tokens(
    headers: dict[str, str],
) -> None:
    with pytest.raises(InvalidAppCheck):
        verify_firebase_app_check(
            headers,
            project_number="123",
            allowed_app_ids={"registered"},
            now=1,
            verify_token=lambda _token, _audience: {},
        )


@pytest.mark.parametrize(
    ("header", "claims", "project_number", "allowed_apps"),
    [
        ({"alg": "HS256", "typ": "JWT"}, {}, "123", {"registered"}),
        ({"alg": "RS256", "typ": "not-jwt"}, {}, "123", {"registered"}),
        (
            {"alg": "RS256", "typ": "JWT"},
            {"aud": ["projects/other"], "iss": "issuer", "sub": "registered", "exp": 2},
            "123",
            {"registered"},
        ),
        (
            {"alg": "RS256", "typ": "JWT"},
            {
                "aud": ["projects/123"],
                "iss": "https://firebaseappcheck.googleapis.com/123",
                "sub": "unregistered",
                "exp": 2,
            },
            "123",
            {"registered"},
        ),
        (
            {"alg": "RS256", "typ": "JWT"},
            {
                "aud": ["projects/123"],
                "iss": "https://firebaseappcheck.googleapis.com/123",
                "sub": "registered",
                "exp": 1,
            },
            "123",
            {"registered"},
        ),
        ({"alg": "RS256", "typ": "JWT"}, {}, "", {"registered"}),
        ({"alg": "RS256", "typ": "JWT"}, {}, "123", set()),
    ],
    ids=[
        "wrong-algorithm",
        "wrong-type",
        "wrong-project",
        "unregistered-app",
        "expired",
        "missing-project",
        "missing-app-allowlist",
    ],
)
def test_verify_app_check_rejects_invalid_headers_claims_and_configuration(
    header: dict[str, Any],
    claims: dict[str, Any],
    project_number: str,
    allowed_apps: set[str],
) -> None:
    token = _token(header)

    with pytest.raises(InvalidAppCheck):
        verify_firebase_app_check(
            {"x-firebase-appcheck": token},
            project_number=project_number,
            allowed_app_ids=allowed_apps,
            now=1,
            verify_token=lambda _token, _audience: claims,
        )


def test_verify_app_check_sanitizes_verifier_and_header_failures() -> None:
    def fail(_token: str, _audience: str) -> Mapping[str, Any]:
        raise RuntimeError("private-app-check-token")

    for token in (_token(), "not-base64.payload.signature"):
        with pytest.raises(InvalidAppCheck) as caught:
            verify_firebase_app_check(
                {"x-firebase-appcheck": token},
                project_number="123",
                allowed_app_ids={"registered"},
                now=1,
                verify_token=fail,
            )
        assert "private-app-check-token" not in str(caught.value)
        assert caught.value.__cause__ is None


def test_google_verifier_uses_app_check_jwks_and_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class Request:
        def __call__(self, **kwargs: Any) -> Any:
            calls.update(kwargs)
            return object()

    def verify_token(
        token: str,
        request: Any,
        *,
        audience: str,
        certs_url: str,
    ) -> Mapping[str, Any]:
        assert token == "signed"
        assert audience == "projects/123"
        assert certs_url == "https://firebaseappcheck.googleapis.com/v1/jwks"
        request(url=certs_url, method="GET")
        return {"sub": "registered"}

    monkeypatch.setattr(app_check_module, "Request", lambda: Request())
    monkeypatch.setattr(app_check_module, "verify_token", verify_token)

    assert app_check_module._verify_google_token("signed", "projects/123") == {
        "sub": "registered"
    }
    assert calls["timeout"] == 5


def test_google_verifier_rejects_non_mapping_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_check_module, "Request", lambda: object())
    monkeypatch.setattr(app_check_module, "verify_token", lambda *_args, **_kwargs: [])

    with pytest.raises(ValueError, match="invalid App Check claims"):
        app_check_module._verify_google_token("signed", "projects/123")
