"""Keep the Open Runtimes event loop free while the synchronous API performs I/O."""

import asyncio
from pathlib import Path
from sys import path as module_search_path
from time import perf_counter, time
from typing import Any

module_search_path.insert(0, str(Path(__file__).resolve().parent))

from main import _log, _validated_request_id  # noqa: E402
from main import main as handle_request


async def main(context: Any) -> Any:
    started = perf_counter()
    request_id = _validated_request_id(context.req.headers)
    fields = {"request_id": request_id, "method": context.req.method}
    _log(context, "runtime_dispatch_received", received_at_ms=int(time() * 1000), **fields)

    def dispatch() -> Any:
        _log(
            context,
            "runtime_handler_started",
            queue_wait_ms=round((perf_counter() - started) * 1000, 3),
            **fields,
        )
        outcome = "raised"
        try:
            result = handle_request(context)
            outcome = "returned"
            return result
        finally:
            _log(
                context,
                "runtime_dispatch_finished",
                outcome=outcome,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                **fields,
            )

    return await asyncio.to_thread(dispatch)
