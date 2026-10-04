"""Cross-service proof that Firestore REST keeps Firebase Security Rules active."""

import json
from os import environ
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from firestore_rest import (
    FirestoreAccessDenied,
    FirestoreNotFound,
    FirestoreRequestRejected,
    FirestoreRestClient,
)

PROJECT_ID = "demo-frequencia-ufmg"

pytestmark = pytest.mark.skipif(
    not environ.get("FIRESTORE_EMULATOR_HOST") or not environ.get("FIREBASE_AUTH_EMULATOR_HOST"),
    reason="Firebase Auth and Firestore emulators are required",
)


def _create_user(label: str) -> tuple[str, str]:
    auth_host = environ["FIREBASE_AUTH_EMULATOR_HOST"]
    request = Request(
        f"http://{auth_host}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-key",
        data=json.dumps(
            {
                "email": f"{label}@example.test",
                "password": "local-test-only",
                "returnSecureToken": True,
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        body = json.loads(response.read())
    return body["localId"], body["idToken"]


def _course_fields() -> dict[str, object]:
    timestamp = {"timestampValue": "2026-07-01T12:00:00Z"}
    return {
        "schemaVersion": {"integerValue": "1"},
        "code": {"stringValue": "DCC203"},
        "name": {"stringValue": "Programação Orientada a Objetos"},
        "workload": {"integerValue": "60"},
        "term": {"stringValue": "2026-2"},
        "startsOn": {"nullValue": None},
        "endsOn": {"nullValue": None},
        "createdAt": timestamp,
        "updatedAt": timestamp,
    }


def test_firestore_rest_enforces_owner_other_user_and_anonymous_rules() -> None:
    owner_id, owner_token = _create_user("rest-owner")
    _other_id, other_token = _create_user("rest-other")
    owner = FirestoreRestClient(PROJECT_ID, owner_id, owner_token)

    created = owner.patch_user_document("courses", "dcc203", fields=_course_fields())
    loaded = owner.get_user_document("courses", "dcc203")

    assert created["fields"]["code"] == {"stringValue": "DCC203"}
    assert loaded["fields"]["name"] == {"stringValue": "Programação Orientada a Objetos"}

    other_targeting_owner = FirestoreRestClient(PROJECT_ID, owner_id, other_token)
    with pytest.raises(FirestoreAccessDenied):
        other_targeting_owner.get_user_document("courses", "dcc203")

    firestore_host = environ["FIRESTORE_EMULATOR_HOST"]
    anonymous_url = (
        f"http://{firestore_host}/v1/projects/{PROJECT_ID}/databases/(default)/"
        f"documents/users/{owner_id}/courses/dcc203"
    )
    with pytest.raises(HTTPError) as anonymous_error:
        urlopen(anonymous_url, timeout=10)
    assert anonymous_error.value.code == 403

    updated_fields = {**_course_fields(), "name": {"stringValue": "POO atualizada"}}
    updated = owner.patch_user_document("courses", "dcc203", fields=updated_fields)
    listed = owner.list_user_documents("courses")
    owner.delete_user_documents([("courses", "dcc203")])

    assert updated["fields"]["name"] == {"stringValue": "POO atualizada"}
    assert [document["fields"]["code"] for document in listed] == [{"stringValue": "DCC203"}]
    with pytest.raises(FirestoreNotFound):
        owner.get_user_document("courses", "dcc203")


def test_firestore_rest_rejects_an_invalid_user_token() -> None:
    client = FirestoreRestClient(PROJECT_ID, "rest-owner", "not-a-jwt")

    with pytest.raises(FirestoreRequestRejected):
        client.get_user_document("courses", "dcc203")
