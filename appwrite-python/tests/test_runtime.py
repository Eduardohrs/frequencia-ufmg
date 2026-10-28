import asyncio
import json
from contextvars import ContextVar
from threading import Event

import pytest
from test_main import FakeContext, FakeRequest

import runtime


def test_long_request_does_not_block_short_request_or_mix_context(monkeypatch):
    entered, release = Event(), Event()
    identity = ContextVar("runtime_test_identity", default="unset")

    def dispatch(context):
        path = context.req.path
        identity.set(path)
        if path == "/internal/academic-sync":
            entered.set()
            assert release.wait(3)
        return {"path": path, "context": identity.get()}

    monkeypatch.setattr(runtime, "handle_request", dispatch)

    async def scenario():
        long = FakeContext(
            FakeRequest("POST", "/internal/academic-sync", headers={"x-request-id": "long"})
        )
        short = FakeContext(FakeRequest("GET", "/v1/identity", headers={"x-request-id": "short"}))
        task = asyncio.create_task(runtime.main(long))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            response = await asyncio.wait_for(runtime.main(short), timeout=1)
            assert response == {"path": "/v1/identity", "context": "/v1/identity"}
            assert not task.done()
        finally:
            release.set()
            assert (await task)["context"] == "/internal/academic-sync"
        assert identity.get() == "unset"
        for ctx, identifier in [(long, "long"), (short, "short")]:
            rows = [json.loads(line) for line in ctx.logs]
            assert [row["event"] for row in rows] == [
                "runtime_dispatch_received",
                "runtime_handler_started",
                "runtime_dispatch_finished",
            ]
            assert all(row["request_id"] == identifier for row in rows)
            assert rows[-1]["duration_ms"] >= 0
            assert rows[1]["queue_wait_ms"] >= 0
            assert rows[-1]["outcome"] == "returned"

    asyncio.run(scenario())


def test_entrypoint_preserves_real_handler_and_failure_diagnostics(monkeypatch):
    real = FakeContext(
        FakeRequest("OPTIONS", "/v1/identity", headers={"x-request-id": "preflight"})
    )
    assert asyncio.run(runtime.main(real))["status"] == 204

    def fail(_context):
        raise ValueError("failure")

    monkeypatch.setattr(runtime, "handle_request", fail)
    ctx = FakeContext(FakeRequest("GET", "/v1/identity"))
    with pytest.raises(ValueError, match="failure"):
        asyncio.run(runtime.main(ctx))
    assert json.loads(ctx.logs[-1])["outcome"] == "raised"
