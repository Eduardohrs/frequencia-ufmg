"""Bounded in-memory PDF extraction used by the Appwrite feasibility gate."""

import re
from datetime import date
from io import BytesIO

from pypdf import PdfReader

MAX_PDF_BYTES = 1_000_000
DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")


def extract_dates(text: str) -> list[str]:
    """Return valid calendar dates in a stable, normalized representation."""

    dates = set()
    for day, month, year in DATE_PATTERN.findall(text):
        try:
            parsed = date(int(year), int(month), int(day))
        except ValueError:
            continue
        dates.add(parsed.strftime("%d/%m/%Y"))
    return sorted(dates, key=lambda value: date.fromisoformat(_to_iso(value)))


def _to_iso(value: str) -> str:
    return f"{value[6:]}-{value[3:5]}-{value[:2]}"


def extract_pdf_summary(payload: bytes) -> dict[str, int | list[str]]:
    """Extract bounded metadata and dates without writing the PDF to storage."""

    if len(payload) > MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the spike limit")
    if not payload.startswith(b"%PDF"):
        raise ValueError("invalid PDF signature")

    reader = PdfReader(BytesIO(payload))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {
        "bytes": len(payload),
        "characters": len(text),
        "dates": extract_dates(text),
        "pages": len(reader.pages),
    }
