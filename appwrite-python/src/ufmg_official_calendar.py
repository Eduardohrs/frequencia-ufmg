"""Bounded reader for the public UFMG school-calendar event contract."""

from collections.abc import Callable, Mapping
from datetime import date
from html.parser import HTMLParser
from time import perf_counter
from types import TracebackType
from typing import Protocol
from unicodedata import combining, normalize
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_BASE_URL = "https://www.ufmg.br/a-universidade/calendario-escolar/"
_MAX_RESPONSE_BYTES = 1_000_000
_MAX_EVENTS = 500


class OfficialCalendarUnavailable(RuntimeError):
    pass


class InvalidOfficialCalendar(ValueError):
    pass


class _Response(Protocol):
    headers: Mapping[str, str]

    def __enter__(self) -> "_Response": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def getcode(self) -> int: ...

    def read(self, amount: int = -1) -> bytes: ...


Transport = Callable[[Request, float], tuple[int, bytes, str]]
Telemetry = Callable[[str, Mapping[str, object]], None]


class OfficialCalendarClient:
    def __init__(
        self,
        *,
        transport: Transport | None = None,
        telemetry: Telemetry | None = None,
    ) -> None:
        self._transport = transport or _urlopen_transport
        self._telemetry = telemetry

    def fetch_month(self, year: int, month: int) -> dict[str, object]:
        started = perf_counter()
        if year < 2026 or year > 2099 or month < 1 or month > 12:
            raise ValueError("unsupported official calendar month")
        url = f"{_BASE_URL}?mes={month:02d}&ano={year}"
        request = Request(url, headers={"Accept": "text/html", "User-Agent": "UFMGManager/1"})
        try:
            status, body, content_type = self._transport(request, 15)
        except (TimeoutError, URLError, OfficialCalendarUnavailable) as error:
            self._failed(
                year,
                month,
                "request",
                "transport_error",
                started=started,
                error_type=type(error).__name__,
            )
            raise OfficialCalendarUnavailable("official calendar unavailable") from error
        if status != 200:
            self._failed(
                year,
                month,
                "upstream_response",
                "http_status",
                started=started,
                upstream_status=status,
            )
            raise OfficialCalendarUnavailable("official calendar unavailable")
        if len(body) > _MAX_RESPONSE_BYTES:
            self._failed(
                year,
                month,
                "response_validation",
                "response_too_large",
                started=started,
                response_bytes=len(body),
            )
            raise InvalidOfficialCalendar("invalid official calendar response")
        if "text/html" not in content_type.lower():
            self._failed(
                year,
                month,
                "response_validation",
                "content_type_invalid",
                started=started,
                content_type=content_type,
            )
            raise InvalidOfficialCalendar("invalid official calendar response")

        parser = _CalendarInputParser()
        try:
            parser.feed(body.decode("utf-8"))
            events = _validated_events(parser.events, year=year, month=month)
        except (UnicodeDecodeError, ValueError) as error:
            self._failed(
                year,
                month,
                "document_parse",
                "invalid_document",
                started=started,
                error_type=type(error).__name__,
            )
            raise InvalidOfficialCalendar("invalid official calendar response") from error
        if not events:
            self._failed(year, month, "document_parse", "no_events", started=started)
            raise InvalidOfficialCalendar("official calendar has no events")

        if self._telemetry is not None:
            self._telemetry(
                "official_calendar_fetch_succeeded",
                {
                    "year": year,
                    "month": month,
                    "response_bytes": len(body),
                    "raw_events": len(parser.events),
                    "events": len(events),
                    "holidays": _effect_count(events, "holiday"),
                    "class_replacements": _effect_count(events, "class_replacement"),
                    "no_assessments": _effect_count(events, "no_assessments"),
                    "duration_ms": round((perf_counter() - started) * 1_000, 3),
                },
            )
        return {
            "year": year,
            "month": month,
            "source": "ufmg_official_calendar",
            "source_url": url,
            "events": events,
        }

    def _failed(
        self,
        year: int,
        month: int,
        stage: str,
        reason: str,
        started: float,
        **details: object,
    ) -> None:
        if self._telemetry is not None:
            self._telemetry(
                "official_calendar_fetch_failed",
                {
                    "year": year,
                    "month": month,
                    "stage": stage,
                    "reason": reason,
                    "duration_ms": round((perf_counter() - started) * 1_000, 3),
                    **details,
                },
            )


class _CalendarInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = {key: value for key, value in attrs if value is not None}
        required = ("data-title", "data-local", "data-start-date", "data-end-date")
        if all(key in values for key in required):
            self.events.append({key: values[key] for key in required})


def _validated_events(
    raw_events: list[dict[str, str]], *, year: int, month: int
) -> list[dict[str, str]]:
    if len(raw_events) > _MAX_EVENTS * 2:
        raise ValueError("too many official calendar events")
    unique: dict[tuple[str, str, date, date], dict[str, str]] = {}
    for raw in raw_events:
        title = " ".join(raw["data-title"].split())
        if not title or len(title) > 500:
            raise ValueError("invalid event title")
        start = _compact_date(raw["data-start-date"])
        end = _compact_date(raw["data-end-date"])
        if start.year != year or start.month != month or end < start or (end - start).days > 31:
            raise ValueError("invalid event range")
        campus = _campus(raw["data-local"])
        key = (title, campus, start, end)
        unique[key] = {
            "title": title,
            "campus": campus,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "effect": _effect(title),
            "confidence": "official",
        }
    if len(unique) > _MAX_EVENTS:
        raise ValueError("too many official calendar events")
    return sorted(unique.values(), key=lambda event: (event["start_date"], event["title"]))


def _compact_date(value: str) -> date:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ValueError("invalid compact date")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _campus(value: str) -> str:
    normalized = _plain(value)
    mapping = {
        "todos os campi": "all",
        "belo horizonte": "belo_horizonte",
        "montes claros": "montes_claros",
    }
    if normalized not in mapping:
        raise ValueError("unknown official calendar campus")
    return mapping[normalized]


def _effect(title: str) -> str:
    plain = _plain(title)
    if plain.startswith("feriado:"):
        return "holiday"
    if "nao devem ocorrer atividades avaliativas" in plain:
        return "no_assessments"
    if "em substituicao as aulas" in plain:
        return "class_replacement"
    return "informational"


def _plain(value: str) -> str:
    return "".join(
        character for character in normalize("NFKD", value).casefold() if not combining(character)
    ).strip()


def _effect_count(events: list[dict[str, str]], effect: str) -> int:
    return sum(event["effect"] == effect for event in events)


def _urlopen_transport(request: Request, timeout: float) -> tuple[int, bytes, str]:
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed UFMG URL
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            return response.getcode(), body, response.headers.get("Content-Type", "")
    except HTTPError as error:
        raise OfficialCalendarUnavailable("official calendar unavailable") from error
