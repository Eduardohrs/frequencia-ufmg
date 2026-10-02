from collections.abc import Mapping
from typing import Any

import pytest

import firebase_identity as identity_module
from firebase_identity import FirebaseIdentity, InvalidIdentity, verify_firebase_identity


def test_verify_firebase_identity_accepts_expected_firebase_claims() -> None:
    def verify_token(token: str, project_id: str) -> Mapping[str, Any]:
        assert token == "signed-id-token"
        assert project_id == "frequencia-ufmg-eduardo"
        return {
            "aud": project_id,
            "iss": f"https://securetoken.google.com/{project_id}",
            "sub": "firebase-user-123",
        }

    identity = verify_firebase_identity(
        {"Authorization": "Bearer signed-id-token"},
        "frequencia-ufmg-eduardo",
        verify_token,
    )

    assert identity == FirebaseIdentity(uid="firebase-user-123")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": ""},
        {"authorization": "Basic credential"},
        {"authorization": "Bearer"},
        {"authorization": "Bearer token extra"},
    ],
)
def test_verify_firebase_identity_rejects_missing_or_malformed_bearer_token(
    headers: dict[str, str],
) -> None:
    with pytest.raises(InvalidIdentity):
        verify_firebase_identity(headers, "project", lambda _token, _project: {})


@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"aud": "other", "iss": "https://securetoken.google.com/project", "sub": "user"},
        {"aud": "project", "iss": "https://issuer.invalid/project", "sub": "user"},
        {"aud": "project", "iss": "https://securetoken.google.com/project", "sub": ""},
        {"aud": "project", "iss": "https://securetoken.google.com/project", "sub": 123},
    ],
)
def test_verify_firebase_identity_rejects_invalid_claims(claims: Mapping[str, Any]) -> None:
    with pytest.raises(InvalidIdentity):
        verify_firebase_identity(
            {"AUTHORIZATION": "Bearer signed-id-token"},
            "project",
            lambda _token, _project: claims,
        )


def test_verify_firebase_identity_sanitizes_verifier_failures() -> None:
    def fail(_token: str, _project_id: str) -> Mapping[str, Any]:
        raise ValueError("signed-id-token")

    with pytest.raises(InvalidIdentity) as caught:
        verify_firebase_identity(
            {"authorization": "Bearer signed-id-token"},
            "project",
            fail,
        )

    assert str(caught.value) == "invalid Firebase identity"
    assert caught.value.__cause__ is None


def test_verify_firebase_identity_requires_project_configuration() -> None:
    with pytest.raises(InvalidIdentity):
        verify_firebase_identity(
            {"authorization": "Bearer signed-id-token"},
            "",
            lambda _token, _project: {},
        )


def test_verify_firebase_identity_rejects_oversized_token_and_uid() -> None:
    with pytest.raises(InvalidIdentity):
        verify_firebase_identity(
            {"authorization": f"Bearer {'x' * 16_385}"},
            "project",
            lambda _token, _project: {},
        )

    with pytest.raises(InvalidIdentity):
        verify_firebase_identity(
            {"authorization": "Bearer signed-id-token"},
            "project",
            lambda _token, project: {
                "aud": project,
                "iss": f"https://securetoken.google.com/{project}",
                "sub": "u" * 129,
            },
        )


def test_google_verifier_uses_official_firebase_certificate_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = object()
    calls: dict[str, Any] = {}
    monkeypatch.setattr(identity_module, "Request", lambda: request)

    def verify(token: str, transport: object, *, audience: str) -> Mapping[str, Any]:
        calls.update(token=token, transport=transport, audience=audience)
        return {"sub": "user"}

    monkeypatch.setattr(identity_module, "verify_firebase_token", verify)

    claims = identity_module._verify_google_token("signed", "project")

    assert claims == {"sub": "user"}
    assert calls == {"token": "signed", "transport": request, "audience": "project"}

    monkeypatch.setattr(identity_module, "verify_firebase_token", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="invalid token claims"):
        identity_module._verify_google_token("signed", "project")
