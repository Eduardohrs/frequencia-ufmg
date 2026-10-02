from io import BytesIO

import pytest
from pypdf import PdfWriter

from pdf_probe import MAX_PDF_BYTES, extract_dates, extract_pdf_summary


def _blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def test_extract_dates_normalizes_valid_unique_dates() -> None:
    assert extract_dates("Prova 2/8/2026, retorno 02-08-2026; inválida 31/02/2026") == [
        "02/08/2026"
    ]


def test_extract_pdf_summary_reads_bounded_pdf_in_memory() -> None:
    payload = _blank_pdf()

    assert extract_pdf_summary(payload) == {
        "bytes": len(payload),
        "characters": 0,
        "dates": [],
        "pages": 1,
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [(b"not a pdf", "invalid PDF signature"), (b"%PDF" + b"x" * MAX_PDF_BYTES, "limit")],
    ids=["invalid-signature", "oversized"],
)
def test_extract_pdf_summary_rejects_invalid_input(payload: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        extract_pdf_summary(payload)
