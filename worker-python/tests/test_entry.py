import importlib
import sys
from types import ModuleType, SimpleNamespace

from worker import app


def test_entry_wraps_the_fastapi_app_with_cloudflare_asgi(monkeypatch) -> None:
    adapter = SimpleNamespace(entrypoint=lambda application: ("entrypoint", application))
    workers = ModuleType("workers")
    workers.asgi = adapter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "workers", workers)

    entry = importlib.import_module("entry")

    assert entry.Default == ("entrypoint", app)
