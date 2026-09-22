"""HTTP entrypoint for the Frequência UFMG backend."""

import logging
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from frequencia_ufmg.logging_config import configure_logging

APP_VERSION = "0.1.0"
configure_logging()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Response returned by the service health endpoint."""

    status: Literal["ok"]
    service: str
    version: str


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request metadata without storing user content or credentials."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach a correlation ID and emit one structured completion record."""

        started_at = monotonic()
        request_id = uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra=_request_fields(request, request_id, 500, started_at),
            )
            raise
        logger.info(
            "request_completed",
            extra=_request_fields(request, request_id, response.status_code, started_at),
        )
        response.headers["x-request-id"] = request_id
        return response


def _request_fields(
    request: Request,
    request_id: str,
    status_code: int,
    started_at: float,
) -> dict[str, object]:
    return {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round((monotonic() - started_at) * 1000, 2),
    }


app = FastAPI(title="Frequência UFMG API", version=APP_VERSION)
app.add_middleware(RequestLoggingMiddleware)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API process is ready to receive requests."""

    return HealthResponse(status="ok", service="frequencia-ufmg", version=APP_VERSION)
