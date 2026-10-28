import json
from copy import deepcopy

import pytest

from academic_sync_job import AcademicSyncJob, InvalidJob, JobCipher
from firestore_rest import FirestoreConflict, FirestoreNotFound


class Store:
    def __init__(self):
        self.doc = None
        self.writes = 0

    def get_user_document(self, *path):
        if self.doc is None:
            raise FirestoreNotFound()
        return deepcopy(self.doc)

    def patch_user_document(self, *path, fields, expected_update_time=None, create_only=False):
        if (
            create_only
            and self.doc
            or expected_update_time
            and self.doc["updateTime"] != expected_update_time
        ):
            raise FirestoreConflict()
        self.writes += 1
        self.doc = {"fields": deepcopy(fields), "updateTime": str(self.writes)}
        return deepcopy(self.doc)


def test_client_disconnect_does_not_cancel_queued_work_and_result_can_be_recovered():
    store = Store()
    events = []
    queued = []
    job = AcademicSyncJob(store, now=lambda: 1000, telemetry=lambda e, f: events.append((e, f)))
    assert job.start("operation-123", lambda: queued.append("execution"))["status"] == "queued"
    # The initiating client is gone; a fresh worker still claims and finishes the job.
    worker = AcademicSyncJob(store, now=lambda: 1100)
    assert worker.claim("operation-123")
    worker.finish("operation-123", {"exceptions": [], "count": 12})
    restored = AcademicSyncJob(store, now=lambda: 1200).read()
    assert restored["status"] == "succeeded"
    assert restored["result"]["count"] == 12
    assert queued == ["execution"]
    assert job.start("operation-123", lambda: None)["status"] == "succeeded"
    assert events[0][0] == "academic_sync_job_queued"


def test_repeated_start_and_delivery_do_not_duplicate_work():
    job = AcademicSyncJob(Store(), now=lambda: 1000)

    def unexpected():
        raise AssertionError("duplicate dispatch")

    job.start("operation-123", lambda: None)
    assert job.start("operation-456", unexpected)["operation_id"] == "operation-123"
    assert job.claim("operation-123")
    assert not job.claim("operation-123")
    assert not job.claim("operation-456")


def test_enqueue_failure_is_persisted_and_can_be_retried():
    job = AcademicSyncJob(Store(), now=lambda: 1000)
    with pytest.raises(RuntimeError):
        job.start("operation-123", lambda: (_ for _ in ()).throw(RuntimeError("private")))
    assert job.read()["failure_code"] == "enqueue_failed"
    job.start("operation-456", lambda: None)
    job.fail("operation-456", "MoodleUnavailable")
    assert job.read()["failure_code"] == "MoodleUnavailable"
    assert "private" not in json.dumps(job.read())


def test_cipher_binds_worker_to_job_and_expires_without_plaintext_credentials():
    cipher = JobCipher({1: b"x" * 32}, 1)
    payload = cipher.seal("user1", "operation-123", "credential", now=1000)
    assert "credential" not in json.dumps(payload)
    assert cipher.open(payload, now=1001) == ("user1", "operation-123", "credential")
    with pytest.raises(InvalidJob):
        cipher.open(payload, now=3000)
    payload["ciphertext"] = "invalid"
    with pytest.raises(InvalidJob):
        cipher.open(payload, now=1001)


def test_stale_job_supersession_and_compare_and_swap_races():
    store = Store()
    clock = [1000]
    job = AcademicSyncJob(store, now=lambda: clock[0])
    assert job.read() == {"status": "missing"}
    job.start("operation-123", lambda: None)
    assert job.start("operation-123", lambda: None)["status"] == "queued"
    clock[0] = 3000
    assert job.read()["failure_code"] == "worker_deadline_exceeded"
    job.start("operation-456", lambda: None)
    job.finish("old-operation", {})
    assert job.read()["operation_id"] == "operation-456"
    original = store.patch_user_document
    store.patch_user_document = lambda *a, **k: (_ for _ in ()).throw(FirestoreConflict())
    assert not job.claim("operation-456")
    clock[0] = 5000
    assert job.start("operation-789", lambda: None)["operation_id"] == "operation-456"
    store.patch_user_document = original


def test_cipher_rejects_malformed_and_authenticated_invalid_payloads():
    from base64 import b64encode

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    cipher = JobCipher({1: b"x" * 32}, 1)
    for value in [None, {}, {"version": 99, "nonce": "", "ciphertext": ""}]:
        with pytest.raises(InvalidJob):
            cipher.open(value, now=1000)
    nonce = b"n" * 12
    for data in [
        ["user", "x", "token", 1000],
        ["user", "operation-123", "", 1000],
        ["user", "operation-123", "token", 1001],
    ]:
        value = {
            "version": 1,
            "nonce": b64encode(nonce).decode(),
            "ciphertext": b64encode(
                AESGCM(b"x" * 32).encrypt(nonce, json.dumps(data).encode(), b"academic-sync-job-v1")
            ).decode(),
        }
        with pytest.raises(InvalidJob):
            cipher.open(value, now=1000)


@pytest.mark.parametrize("force", [False, True])
def test_http_dispatch_worker_and_recovery_without_original_client(monkeypatch, force):
    from base64 import b64encode

    from test_main import FakeContext, FakeRequest

    import main as function

    monkeypatch.setenv("UFMG_SESSION_ACTIVE_KEY_VERSION", "1")
    monkeypatch.setenv("UFMG_SESSION_ENCRYPTION_KEY_V1", b64encode(b"x" * 32).decode())
    monkeypatch.setenv("UFMG_SESSION_INDEX_KEY", b64encode(b"y" * 32).decode())
    monkeypatch.setenv("APPWRITE_FUNCTION_API_ENDPOINT", "https://example.test/v1")
    monkeypatch.setenv("APPWRITE_FUNCTION_PROJECT_ID", "test-project")
    monkeypatch.setenv("APPWRITE_FUNCTION_ID", "test-function")
    monkeypatch.setenv("ENABLE_SCHEDULE_WRITES", "true")
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    stores = {}

    class RoutedStore:
        def get_user_document(self, *path):
            return stores.setdefault(path, Store()).get_user_document()

        def patch_user_document(self, *path, **kwargs):
            return stores.setdefault(path, Store()).patch_user_document(**kwargs)

    store = RoutedStore()
    monkeypatch.setattr(function, "_firestore", lambda *_: store)
    captured = []

    class Functions:
        def __init__(self, client):
            pass

        def create_execution(self, **args):
            captured.append(args)
            from types import SimpleNamespace

            return SimpleNamespace(id="execution-test123")

    monkeypatch.setattr(function, "Functions", Functions)
    request = FakeContext(
        FakeRequest(
            "POST",
            "/v1/ufmg/sync/all",
            body_json={"progress_id": "operation-123", "background": True, "force": force},
            headers={"authorization": "Bearer test-user-credential"},
        )
    )
    assert function.main(request)["status"] == 202
    assert captured[0]["xasync"] is True
    assert "test-user-credential" not in captured[0]["body"]

    class Service:
        def __init__(self, telemetry):
            self.telemetry = telemetry

        def sync(self, *a, **k):
            self.telemetry("academic_sync_stage_completed", {"stage": "siga"})
            return {"exceptions": []}

    monkeypatch.setattr(function, "_unified_academic_sync_service", lambda *a, **kw: Service(a[-1]))
    worker = FakeContext(
        FakeRequest("POST", "/internal/academic-sync", body_json=json.loads(captured[0]["body"]))
    )
    assert function.main(worker)["body"] == {"completed": True}
    assert function.main(worker)["body"] == {"accepted": False}
    status = FakeContext(FakeRequest("GET", "/v1/ufmg/sync/job"))
    assert function.main(status)["body"]["result"] == {"exceptions": []}
    # An unrelated HTTP request cannot invoke the worker by guessing its route.
    bad = FakeContext(FakeRequest("POST", "/internal/academic-sync", body_json={}))
    assert function.main(bad)["status"] == 403
    # Failed workers persist a terminal reason without dumping exception messages.
    request.req.body_json["progress_id"] = "operation-456"
    function.main(request)

    class Failure:
        def sync(self, *a, **k):
            raise RuntimeError("never log private credentials")

    monkeypatch.setattr(function, "_unified_academic_sync_service", lambda *a, **kw: Failure())
    worker.req.body_json = json.loads(captured[-1]["body"])
    assert function.main(worker)["status"] == 500
    assert function.main(status)["body"]["failure_code"] == "RuntimeError"
    assert "never log private" not in str(worker.logs + worker.errors)
    # Auth, persistence and queue failure paths are distinct.
    monkeypatch.setattr(function, "_authentication", lambda *_: (None, {"status": 401}))
    assert function.main(status)["status"] == 401
    monkeypatch.setattr(function, "_authentication", lambda *_: ("user", None))
    from firestore_rest import FirestoreUnavailable

    monkeypatch.setattr(
        function, "_sync_job", lambda *a: (_ for _ in ()).throw(FirestoreUnavailable())
    )
    assert function.main(status)["status"] == 503


def test_enqueue_failure_returns_diagnostic_response(monkeypatch):
    from test_main import FakeContext, FakeRequest

    import main as function

    class Job:
        def start(self, *args):
            raise RuntimeError("queue down")

    monkeypatch.setattr(function, "_sync_job", lambda *_: Job())
    c = FakeContext(FakeRequest("POST", "/v1/ufmg/sync/all"))
    assert function._enqueue_academic_sync(c, None, "user", {})["status"] == 503


def test_sdk_dispatch_serializes_a_real_asynchronous_execution_contract():
    from appwrite.client import Client
    from appwrite.enums.execution_method import ExecutionMethod
    from appwrite.services.functions import Functions

    calls = []

    class Sent(Exception):
        pass

    class Transport(Client):
        def call(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise Sent()

    with pytest.raises(Sent):
        Functions(Transport()).create_execution(
            function_id="function",
            body="ciphertext",
            xasync=True,
            path="/internal/academic-sync",
            method=ExecutionMethod.POST,
        )
    assert calls[0][0][3]["async"] is True
    assert calls[0][0][3]["path"] == "/internal/academic-sync"


def test_worker_claim_and_terminal_state_failures_remain_distinguishable(monkeypatch):
    from types import SimpleNamespace

    from test_main import FakeContext, FakeRequest

    import main as function
    from firestore_rest import FirestoreUnavailable

    monkeypatch.setattr(
        function,
        "_job_cipher",
        lambda: SimpleNamespace(open=lambda *a, **k: ("user", "operation-123", "token")),
    )
    monkeypatch.setattr(function, "_firestore", lambda *_: Store())

    class Job:
        def claim(self, operation):
            raise FirestoreUnavailable()

    monkeypatch.setattr(function, "_sync_job", lambda *a: Job())
    context = FakeContext(FakeRequest("POST", "/internal/academic-sync"))
    assert function.main(context)["status"] == 503
    assert "academic_sync_worker_claim_failed" in str(context.errors)

    class Running:
        def claim(self, operation):
            return True

        def fail(self, *args):
            raise FirestoreUnavailable()

    monkeypatch.setattr(function, "_sync_job", lambda *a: Running())
    monkeypatch.setattr(
        function, "_unified_academic_sync_service", lambda *a: (_ for _ in ()).throw(RuntimeError())
    )
    assert function.main(context)["status"] == 500
    assert "academic_sync_worker_state_delivery_failed" in str(context.errors)
    assert "academic_sync_worker_failed" in str(context.errors)
