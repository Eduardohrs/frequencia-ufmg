from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from ufmg_official_calendar import (
    InvalidOfficialCalendar,
    OfficialCalendarClient,
    OfficialCalendarUnavailable,
)

HTML = b"""
<html><body>
  <input type="checkbox" data-title="Feriado: Nossa Senhora Aparecida."
    data-local="Todos os campi" data-start-date="20261012" data-end-date="20261012">
  <input type="checkbox" data-title="Feriado: Nossa Senhora Aparecida."
    data-local="Todos os campi" data-start-date="20261012" data-end-date="20261012">
  <input type="checkbox"
    data-title="Semana do Conhecimento. Nao devem ocorrer atividades avaliativas."
    data-local="Belo Horizonte" data-start-date="20261021" data-end-date="20261024">
  <input type="checkbox" data-title="Atividades complementares em substituicao as aulas."
    data-local="Todos os campi" data-start-date="20261014" data-end-date="20261014">
  <input type="checkbox" data-title="Data-limite de matricula."
    data-local="Montes Claros" data-start-date="20261016" data-end-date="20261016">
</body></html>
"""


def test_fetches_deduplicates_and_classifies_one_official_month() -> None:
    requests: list[tuple[Request, float]] = []
    telemetry: list[tuple[str, dict[str, object]]] = []

    def transport(request: Request, timeout: float) -> tuple[int, bytes, str]:
        requests.append((request, timeout))
        return 200, HTML, "text/html; charset=UTF-8"

    result = OfficialCalendarClient(
        transport=transport,
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    ).fetch_month(2026, 10)

    assert requests[0][0].full_url.endswith("?mes=10&ano=2026")
    assert requests[0][1] == 15
    assert result == {
        "year": 2026,
        "month": 10,
        "source": "ufmg_official_calendar",
        "source_url": "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2026",
        "events": [
            {
                "title": "Feriado: Nossa Senhora Aparecida.",
                "campus": "all",
                "start_date": "2026-10-12",
                "end_date": "2026-10-12",
                "effect": "holiday",
                "confidence": "official",
            },
            {
                "title": "Atividades complementares em substituicao as aulas.",
                "campus": "all",
                "start_date": "2026-10-14",
                "end_date": "2026-10-14",
                "effect": "class_replacement",
                "confidence": "official",
            },
            {
                "title": "Data-limite de matricula.",
                "campus": "montes_claros",
                "start_date": "2026-10-16",
                "end_date": "2026-10-16",
                "effect": "informational",
                "confidence": "official",
            },
            {
                "title": "Semana do Conhecimento. Nao devem ocorrer atividades avaliativas.",
                "campus": "belo_horizonte",
                "start_date": "2026-10-21",
                "end_date": "2026-10-24",
                "effect": "no_assessments",
                "confidence": "official",
            },
        ],
    }
    assert telemetry == [
        (
            "official_calendar_fetch_succeeded",
            {
                "year": 2026,
                "month": 10,
                "response_bytes": len(HTML),
                "raw_events": 5,
                "events": 4,
                "holidays": 1,
                "class_replacements": 1,
                "no_assessments": 1,
            },
        )
    ]


@pytest.mark.parametrize("year,month", [(2025, 10), (2100, 10), (2026, 0), (2026, 13)])
def test_rejects_unsupported_months(year: int, month: int) -> None:
    with pytest.raises(ValueError):
        OfficialCalendarClient(transport=lambda *_: (200, HTML, "text/html")).fetch_month(
            year, month
        )


@pytest.mark.parametrize(
    "response",
    [
        (503, b"down", "text/html"),
        (200, b"x" * 1_000_001, "text/html"),
        (200, HTML, "application/json"),
        (200, b"<html></html>", "text/html"),
        (200, b'<input data-title="Incomplete">', "text/html"),
        (200, b"\xff", "text/html"),
        (
            200,
            b'<input data-title="" data-local="Todos os campi" '
            b'data-start-date="20261012" data-end-date="20261012">',
            "text/html",
        ),
        (
            200,
            b'<input data-title="Unknown campus" data-local="Outro" '
            b'data-start-date="20261012" data-end-date="20261012">',
            "text/html",
        ),
        (
            200,
            b'<input data-title="Broken" data-local="Todos os campi" '
            b'data-start-date="bad" data-end-date="20261012">',
            "text/html",
        ),
        (
            200,
            b'<input data-title="Backwards" data-local="Todos os campi" '
            b'data-start-date="20261013" data-end-date="20261012">',
            "text/html",
        ),
    ],
)
def test_rejects_unavailable_or_malformed_responses(
    response: tuple[int, bytes, str],
) -> None:
    client = OfficialCalendarClient(transport=lambda *_: response)
    error = OfficialCalendarUnavailable if response[0] != 200 else InvalidOfficialCalendar
    with pytest.raises(error):
        client.fetch_month(2026, 10)


@pytest.mark.parametrize("failure", [URLError("offline"), TimeoutError()])
def test_maps_transport_failures_without_exposing_the_request(failure: Exception) -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []

    def transport(*_args: object) -> tuple[int, bytes, str]:
        raise failure

    with pytest.raises(OfficialCalendarUnavailable):
        OfficialCalendarClient(
            transport=transport,
            telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
        ).fetch_month(2026, 10)
    assert telemetry == [
        (
            "official_calendar_fetch_failed",
            {
                "year": 2026,
                "month": 10,
                "stage": "request",
                "reason": "transport_error",
                "error_type": type(failure).__name__,
            },
        )
    ]


@pytest.mark.parametrize(
    "response,stage,reason,detail",
    [
        ((503, b"down", "text/html"), "upstream_response", "http_status", ("upstream_status", 503)),
        (
            (200, b"x" * 1_000_001, "text/html"),
            "response_validation",
            "response_too_large",
            ("response_bytes", 1_000_001),
        ),
        (
            (200, HTML, "application/json"),
            "response_validation",
            "content_type_invalid",
            ("content_type", "application/json"),
        ),
        ((200, b"<html></html>", "text/html"), "document_parse", "no_events", None),
        (
            (200, b"\xff", "text/html"),
            "document_parse",
            "invalid_document",
            ("error_type", "UnicodeDecodeError"),
        ),
    ],
)
def test_failure_telemetry_identifies_the_exact_stage(
    response: tuple[int, bytes, str],
    stage: str,
    reason: str,
    detail: tuple[str, object] | None,
) -> None:
    telemetry: list[tuple[str, dict[str, object]]] = []
    client = OfficialCalendarClient(
        transport=lambda *_: response,
        telemetry=lambda event, fields: telemetry.append((event, dict(fields))),
    )

    with pytest.raises((OfficialCalendarUnavailable, InvalidOfficialCalendar)):
        client.fetch_month(2026, 10)

    fields = {"year": 2026, "month": 10, "stage": stage, "reason": reason}
    if detail is not None:
        fields[detail[0]] = detail[1]
    assert telemetry == [("official_calendar_fetch_failed", fields)]


def test_default_transport_maps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import ufmg_official_calendar as module

    def fail(*_args: object, **_kwargs: object) -> None:
        raise HTTPError("url", 404, "missing", {}, None)

    monkeypatch.setattr(module, "urlopen", fail)
    with pytest.raises(OfficialCalendarUnavailable):
        OfficialCalendarClient().fetch_month(2026, 10)


def test_rejects_raw_and_unique_event_limits() -> None:
    duplicate = (
        b'<input data-title="Holiday" data-local="Todos os campi" '
        b'data-start-date="20261012" data-end-date="20261012">'
    )
    with pytest.raises(InvalidOfficialCalendar):
        OfficialCalendarClient(
            transport=lambda *_: (200, duplicate * 1001, "text/html")
        ).fetch_month(2026, 10)

    unique = b"".join(
        b'<input data-title="Event ' + str(index).encode() + b'" data-local="Todos os campi" '
        b'data-start-date="20261012" data-end-date="20261012">'
        for index in range(501)
    )
    with pytest.raises(InvalidOfficialCalendar):
        OfficialCalendarClient(transport=lambda *_: (200, unique, "text/html")).fetch_month(
            2026, 10
        )


def test_default_transport_reads_one_bounded_html_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ufmg_official_calendar as module

    class Response:
        headers = {"Content-Type": "text/html"}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def read(self, amount: int = -1) -> bytes:
            assert amount == 1_000_001
            return HTML

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response())

    result = OfficialCalendarClient().fetch_month(2026, 10)

    assert len(result["events"]) == 4
