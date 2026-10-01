from io import BytesIO

import pytest
from pypdf import PdfWriter

from pdf_probe import MAX_PDF_BYTES, extract_dates, extract_pdf_summary


def test_extract_dates_normalizes_and_deduplicates_supported_dates() -> None:
    text = (
        "Prova: 1/10/2026. Trabalho: 01-10-2026. "
        "Revisão: 31.12.2026. Inválida: 31/02/2026."
    )

    assert extract_dates(text) == ["01/10/2026", "31/12/2026"]


def test_extract_pdf_summary_reads_a_valid_pdf_without_persisting_it() -> None:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(buffer)

    assert extract_pdf_summary(buffer.getvalue()) == {
        "bytes": len(buffer.getvalue()),
        "characters": 0,
        "dates": [],
        "pages": 1,
    }


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not a pdf", "invalid PDF signature"),
        (b"%PDF" + b"0" * MAX_PDF_BYTES, "PDF exceeds the spike limit"),
    ],
    ids=("invalid-signature", "oversized"),
)
def test_extract_pdf_summary_rejects_invalid_or_oversized_input(
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        extract_pdf_summary(payload)
