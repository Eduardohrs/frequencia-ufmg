"""HTTP entrypoint for the Frequência UFMG backend."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

APP_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    """Response returned by the service health endpoint."""

    status: Literal["ok"]
    service: str
    version: str


app = FastAPI(title="Frequência UFMG API", version=APP_VERSION)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API process is ready to receive requests."""

    return HealthResponse(status="ok", service="frequencia-ufmg", version=APP_VERSION)

