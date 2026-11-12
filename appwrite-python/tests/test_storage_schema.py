"""Tests for the OPTIONAL operator-run schema module (storage_schema).

The versioned collection specs and the idempotent ensure/validate helpers are used
only by setup_storage.py, run manually against an EXPLICIT target database — never
by the runtime bundle, CI, or the production deploy. Real SDK 27.1.0 services run
against the fake transport harness shared from test_appwrite_storage.
"""

import pytest
from appwrite.services.databases import Databases
from test_appwrite_storage import StorageServer, _err
from test_pendency_repository import FakeTransport, make_client

from appwrite_storage import (
    DRAFT_COLLECTION_ID,
    PENDENCY_COLLECTION_ID,
    StorageNotProvisioned,
    StorageUnavailable,
)
from storage_schema import (
    COLLECTION_SPECS,
    ensure_appwrite_storage,
    validate_appwrite_storage,
    wait_for_spec_ready,
)

TEST_DATABASE_ID = "test-database"


FAST_WAIT = {
    "sleep": lambda *_args: None,
    "poll_interval_seconds": 0.01,
    "timeout_seconds": 0.05,
}


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[Databases, StorageServer, FakeTransport]:
    server = StorageServer()
    client, transport = make_client(monkeypatch, server)
    return Databases(client), server, transport


def test_ensure_creates_database_collections_attributes_and_indexes_idempotently(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    summary = ensure_appwrite_storage(databases, TEST_DATABASE_ID)
    assert summary["database"] == "created"
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "created"}
    assert summary["collections"][DRAFT_COLLECTION_ID] == {"status": "created"}
    assert len(server.create_collection_calls) == 2
    call = server.create_collection_calls[0]
    assert call["collectionId"] == PENDENCY_COLLECTION_ID
    assert call["documentSecurity"] is True
    assert call["permissions"] == []
    assert {attribute["key"] for attribute in call["attributes"]} >= {"user_id", "course_id"}
    assert {index["key"] for index in call["indexes"]} >= {"idx_user_id"}

    # Second run is a no-op: everything already exists.
    again = ensure_appwrite_storage(databases, TEST_DATABASE_ID)
    assert again["database"] == "exists"
    assert again["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}
    assert again["collections"][DRAFT_COLLECTION_ID] == {"status": "exists"}
    assert len(server.create_collection_calls) == 2


def test_ensure_backfills_missing_attributes_and_indexes_on_existing_collection(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)
    server.attributes[PENDENCY_COLLECTION_ID]["user_id"] = "string"
    server.indexes[PENDENCY_COLLECTION_ID]["idx_user_id"] = ["user_id"]
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]

    summary = ensure_appwrite_storage(
        databases, TEST_DATABASE_ID, collections={PENDENCY_COLLECTION_ID: spec}
    )

    assert summary["database"] == "exists"
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}
    assert set(server.attributes[PENDENCY_COLLECTION_ID]) == {a["key"] for a in spec["attributes"]}
    assert set(server.indexes[PENDENCY_COLLECTION_ID]) == {i["key"] for i in spec["indexes"]}

    # integer attribute path (attempt_count in the draft spec)
    server.add_collection(DRAFT_COLLECTION_ID)
    ensure_appwrite_storage(
        databases,
        TEST_DATABASE_ID,
        collections={DRAFT_COLLECTION_ID: COLLECTION_SPECS[DRAFT_COLLECTION_ID]}
    )
    assert server.attributes[DRAFT_COLLECTION_ID]["attempt_count"] == "integer"


def test_ensure_tolerates_409_races_and_classifies_real_failures(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    single = {PENDENCY_COLLECTION_ID: spec}

    # database get fails with non-404 -> unavailable
    server.fail_get_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    # database created between get and create -> 409 race is fine
    server.fail_get_db = _err(404, "database_not_found")
    server.fail_create_db = _err(409, "database_already_exists")
    again = ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    assert again["database"] == "exists"
    server.fail_create_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)

    server.fail_get_db = None
    server.fail_create_db = None
    server.databases.add(TEST_DATABASE_ID)
    # collection get fails with non-404 -> unavailable
    server.fail_get_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    # collection create fails hard -> unavailable; 409 race falls back to backfill
    server.fail_get_collection = _err(404, "collection_not_found")
    server.fail_create_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    server.fail_create_collection = _err(409, "collection_already_exists")
    server.add_collection(PENDENCY_COLLECTION_ID)
    summary = ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}


def test_ensure_backfill_classifies_attribute_and_index_failures(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    single = {PENDENCY_COLLECTION_ID: spec}

    server.fail_list_attributes = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    server.fail_list_attributes = None

    # 409 on attribute create is a race, not a failure
    for attribute in spec["attributes"]:
        server.attributes[PENDENCY_COLLECTION_ID][attribute["key"]] = attribute["type"]
    server.fail_create_attribute = _err(409, "attribute_already_exists")
    # the readiness wait lists indexes once; fail the second listing (inside
    # _ensure_indexes) so that branch is exercised too
    index_lists = {"n": 0}

    def fail_second_list(_collection_id: str) -> None:
        index_lists["n"] += 1
        if index_lists["n"] >= 2:
            raise _err(500, "general")

    server.on_list_indexes = fail_second_list
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    server.on_list_indexes = None
    server.fail_create_attribute = _err(500, "general")
    server.attributes[PENDENCY_COLLECTION_ID] = {}
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    server.fail_create_attribute = None

    for attribute in spec["attributes"]:
        server.attributes[PENDENCY_COLLECTION_ID][attribute["key"]] = attribute["type"]
    for index in spec["indexes"]:
        server.indexes[PENDENCY_COLLECTION_ID][index["key"]] = list(index["attributes"])
    server.fail_create_index = _err(409, "index_already_exists")
    ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)
    server.fail_create_index = _err(500, "general")
    server.indexes[PENDENCY_COLLECTION_ID] = {}
    with pytest.raises(StorageUnavailable):
        ensure_appwrite_storage(databases, TEST_DATABASE_ID, collections=single)


def test_ensure_backfills_integer_attributes_and_tolerates_create_races(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    for collection_id in COLLECTION_SPECS:
        server.add_collection(collection_id)  # empty attributes/indexes

    # 409 races on attribute/index creation are tolerated (concurrent provisioning)
    server.fail_create_attribute = _err(409, "attribute_already_exists")
    server.fail_create_index = _err(409, "index_already_exists")
    summary = ensure_appwrite_storage(databases, TEST_DATABASE_ID)
    assert summary["database"] == "exists"
    assert all(value == {"status": "exists"} for value in summary["collections"].values())

    # real backfill creates string AND integer attributes (attempt_count)
    server.fail_create_attribute = None
    server.fail_create_index = None
    ensure_appwrite_storage(databases, TEST_DATABASE_ID)
    for collection_id, spec in COLLECTION_SPECS.items():
        assert set(server.attributes[collection_id]) == {a["key"] for a in spec["attributes"]}
        assert set(server.indexes[collection_id]) == {i["key"] for i in spec["indexes"]}
    assert server.attributes[DRAFT_COLLECTION_ID]["attempt_count"] == "integer"


def test_validate_reports_missing_database_collections_and_failures(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    # database missing -> 404 database_not_found -> not provisioned
    with pytest.raises(StorageNotProvisioned):
        validate_appwrite_storage(databases, TEST_DATABASE_ID)
    server.fail_get_db = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(databases, TEST_DATABASE_ID)
    server.fail_get_db = None
    server.databases.add(TEST_DATABASE_ID)
    server.fail_get_collection = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(databases, TEST_DATABASE_ID)
    server.fail_get_collection = None
    server.add_collection(PENDENCY_COLLECTION_ID, COLLECTION_SPECS[PENDENCY_COLLECTION_ID])
    with pytest.raises(StorageNotProvisioned) as excinfo:
        validate_appwrite_storage(databases, TEST_DATABASE_ID)  # draft collection missing
    assert DRAFT_COLLECTION_ID in str(excinfo.value)


def test_validate_reports_missing_attributes_and_indexes(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    for collection_id, spec in COLLECTION_SPECS.items():
        server.add_collection(collection_id, spec)
    # drop one attribute and one index from the pendency collection
    del server.attributes[PENDENCY_COLLECTION_ID]["reason"]
    del server.indexes[PENDENCY_COLLECTION_ID]["idx_user_course"]

    with pytest.raises(StorageNotProvisioned) as excinfo:
        validate_appwrite_storage(databases, TEST_DATABASE_ID, **FAST_WAIT)
    message = str(excinfo.value)
    assert "reason" in message
    assert "idx_user_course" in message
    assert "missing" in message

    # attribute/index listing failures propagate as unavailable
    server.fail_list_attributes = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(databases, TEST_DATABASE_ID, **FAST_WAIT)
    server.fail_list_attributes = None
    server.fail_list_indexes = _err(500, "general")
    with pytest.raises(StorageUnavailable):
        validate_appwrite_storage(databases, TEST_DATABASE_ID, **FAST_WAIT)
    server.fail_list_indexes = None


def test_validate_succeeds_when_database_collections_attributes_and_indexes_exist(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    for collection_id, spec in COLLECTION_SPECS.items():
        server.add_collection(collection_id, spec)
    assert validate_appwrite_storage(databases, TEST_DATABASE_ID) == {
        "database": TEST_DATABASE_ID,
        "collections": sorted(COLLECTION_SPECS),
    }


def test_validate_waits_for_processing_resources_until_available(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    for collection_id, spec in COLLECTION_SPECS.items():
        server.add_collection(collection_id, spec)
    for collection_id in COLLECTION_SPECS:
        for key in server.attributes[collection_id]:
            server.attribute_meta[(collection_id, key)] = ("processing", "still building")
        for key in server.indexes[collection_id]:
            server.index_meta[(collection_id, key)] = ("processing", "")
    polls = {"n": 0}

    def flip_to_available(_collection_id: str) -> None:
        polls["n"] += 1
        if polls["n"] < 2:
            return
        for collection_id in COLLECTION_SPECS:
            for key in server.attributes[collection_id]:
                server.attribute_meta[(collection_id, key)] = ("available", "")
            for key in server.indexes[collection_id]:
                server.index_meta[(collection_id, key)] = ("available", "")

    server.on_list_attributes = flip_to_available
    sleeps: list[float] = []
    result = validate_appwrite_storage(
        databases,
        TEST_DATABASE_ID,
        sleep=sleeps.append,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
    )
    assert result == {"database": TEST_DATABASE_ID, "collections": sorted(COLLECTION_SPECS)}
    assert polls["n"] >= 2
    assert sleeps  # the validator actually waited between polls


def test_validate_fails_fast_on_failed_and_stuck_resources(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    for collection_id, spec in COLLECTION_SPECS.items():
        server.add_collection(collection_id, spec)

    server.attribute_meta[(PENDENCY_COLLECTION_ID, "user_id")] = ("failed", "size too small")
    with pytest.raises(StorageNotProvisioned) as excinfo:
        validate_appwrite_storage(databases, TEST_DATABASE_ID, **FAST_WAIT)
    message = str(excinfo.value)
    assert "user_id" in message and "failed" in message and "size too small" in message

    server.attribute_meta[(PENDENCY_COLLECTION_ID, "user_id")] = ("available", "")
    server.index_meta[(PENDENCY_COLLECTION_ID, "idx_user_id")] = ("stuck", "index stuck")
    with pytest.raises(StorageNotProvisioned) as excinfo:
        validate_appwrite_storage(databases, TEST_DATABASE_ID, **FAST_WAIT)
    assert "idx_user_id" in str(excinfo.value) and "stuck" in str(excinfo.value)


def test_wait_for_spec_ready_times_out_listing_not_ready_resources(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    server.add_collection(PENDENCY_COLLECTION_ID, spec)
    server.attribute_meta[(PENDENCY_COLLECTION_ID, "reason")] = ("processing", "still building")

    sleeps: list[float] = []
    with pytest.raises(StorageNotProvisioned) as excinfo:
        wait_for_spec_ready(
            databases,
            TEST_DATABASE_ID,
            PENDENCY_COLLECTION_ID,
            spec,
            sleep=sleeps.append,
            poll_interval_seconds=0.01,
            timeout_seconds=0.05,
        )
    message = str(excinfo.value)
    assert "not ready" in message
    assert "reason" in message and "processing" in message and "still building" in message
    assert len(sleeps) == 4  # 5 attempts (0.05/0.01), sleeping between them

    # single-attempt budget: no sleep, immediate timeout
    with pytest.raises(StorageNotProvisioned):
        wait_for_spec_ready(
            databases,
            TEST_DATABASE_ID,
            PENDENCY_COLLECTION_ID,
            spec,
            sleep=lambda *_args: None,
            poll_interval_seconds=0.01,
            timeout_seconds=0.01,
        )


def test_ensure_waits_for_attributes_available_before_creating_indexes(
    harness: tuple[Databases, StorageServer, FakeTransport],
) -> None:
    databases, server, _ = harness
    server.databases.add(TEST_DATABASE_ID)
    server.add_collection(PENDENCY_COLLECTION_ID)  # exists, empty
    spec = COLLECTION_SPECS[PENDENCY_COLLECTION_ID]
    server.new_attributes_processing = True  # created attributes start "processing"
    polls = {"n": 0}

    def flip(_collection_id: str) -> None:
        polls["n"] += 1
        if polls["n"] < 2:
            return
        for key in server.attributes[PENDENCY_COLLECTION_ID]:
            server.attribute_meta[(PENDENCY_COLLECTION_ID, key)] = ("available", "")

    server.on_list_attributes = flip
    summary = ensure_appwrite_storage(
        databases,
        TEST_DATABASE_ID,
        collections={PENDENCY_COLLECTION_ID: spec},
        sleep=lambda *_args: None,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
    )
    assert summary["collections"][PENDENCY_COLLECTION_ID] == {"status": "exists"}
    assert polls["n"] >= 2  # readiness was polled after backfill
    # every index was created only once all attributes were available
    assert server.attribute_ready_at_index_create
    assert all(server.attribute_ready_at_index_create)

