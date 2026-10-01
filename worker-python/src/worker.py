"""FastAPI entrypoint for the Cloudflare Python feasibility gate."""

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from domain_probe import AttendanceStatus, calculate_absences
from pdf_probe import extract_pdf_summary

app = FastAPI(title="Frequência UFMG Cloudflare Spike", version="0.1.0")


class DomainProbeRequest(BaseModel):
    """Small domain request representative of the production rules."""

    status: AttendanceStatus
    lessons: Literal[1, 2, 4]
    calls: Literal[1, 2]


async def _d1_is_ready(request: Request) -> bool:
    row = await request.scope["env"].DB.prepare("SELECT 1 AS ok").first()
    return bool(row.ok)


@app.get("/v1/spike/health")
async def health(request: Request) -> dict[str, str | bool]:
    """Prove that FastAPI and the D1 binding execute together."""

    return {"d1": await _d1_is_ready(request), "runtime": "python", "status": "ok"}


@app.post("/v1/spike/domain")
async def domain_probe(payload: DomainProbeRequest, request: Request) -> dict[str, int | bool]:
    """Execute one real attendance rule while touching D1."""

    try:
        absences = calculate_absences(payload.status, payload.lessons, payload.calls)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"absences": absences, "d1": await _d1_is_ready(request)}


@app.post("/v1/spike/pdf")
async def pdf_probe(request: Request) -> dict[str, int | list[str]]:
    """Parse a bounded PDF entirely in memory and discard the bytes."""

    if request.headers.get("content-type", "").split(";", 1)[0] != "application/pdf":
        raise HTTPException(status_code=415, detail="application/pdf required")
    try:
        return extract_pdf_summary(await request.body())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
