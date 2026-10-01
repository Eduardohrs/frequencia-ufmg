"""Cloudflare ASGI adapter kept separate from the testable FastAPI app."""

from workers import asgi  # type: ignore[attr-defined]

from worker import app

Default = asgi.entrypoint(app)
