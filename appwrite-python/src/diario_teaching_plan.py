"""Extract bounded structured facts from an official UFMG Diário teaching plan."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

_TERM = re.compile(r"(20[2-9][0-9])\s*[/.-]\s*([12])")
_COURSE = re.compile(r"([A-Z]{3}[0-9]{3})\s+(.{1,160})")
_TIME_RANGE = re.compile(r"([0-2][0-9]:[0-5][0-9])\s*-\s*([0-2][0-9]:[0-5][0-9])")
_MAX_ROWS = 1_000
_MAX_CELLS = 12
_MAX_TEXT = 500


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join(" ".join(self._cell).split())
            if len(value) > _MAX_TEXT or len(self._row) >= _MAX_CELLS:
                raise ValueError("invalid teaching plan")
            self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                if len(self.rows) >= _MAX_ROWS:
                    raise ValueError("invalid teaching plan")
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def parse_teaching_plan_html(markup: str) -> dict[str, object]:
    if not markup or len(markup) > 20 * 1_048_576:
        raise ValueError("invalid teaching plan")
    parser = _TableParser()
    parser.feed(markup)
    rows = parser.rows
    term = _label_value(rows, "periodo")
    activity = _label_value(rows, "atividade")
    class_group = _label_value(rows, "turma")
    term_match = _TERM.fullmatch(term)
    course_match = _COURSE.fullmatch(activity)
    if term_match is None or course_match is None or not class_group:
        raise ValueError("invalid teaching plan")

    assessments: list[dict[str, object]] = []
    criteria: list[dict[str, str]] = []
    schedule: list[dict[str, object]] = []
    section: str | None = None
    for row in rows:
        normalized = [_normalized(cell) for cell in row]
        if normalized[:7] == ["cod.", "tipo", "nome", "data/hora", "local", "valor", "peso"]:
            section = "assessments"
            continue
        if normalized[:2] == ["descricao", "valor parcial"]:
            section = "criteria"
            continue
        if normalized[:7] == [
            "aula",
            "data",
            "dia",
            "num. aulas",
            "horario",
            "tipo",
            "assunto",
        ]:
            section = "schedule"
            continue
        if section == "assessments" and len(row) == 7:
            assessments.append(_assessment(row))
        elif section == "criteria" and len(row) == 2:
            criteria.append({"description": _required(row[0]), "value": _decimal(row[1])})
        elif section == "schedule" and len(row) == 7:
            schedule.append(_schedule_entry(row))

    if not assessments or not criteria or not schedule:
        raise ValueError("invalid teaching plan")
    return {
        "term": f"{term_match[1]}-{term_match[2]}",
        "course_code": course_match[1],
        "course_name": _required(course_match[2]),
        "class_group": _required(class_group),
        "assessments": assessments,
        "criteria": criteria,
        "schedule": schedule,
        "source": "ufmg_diario",
        "confidence": "authoritative",
    }


def _label_value(rows: list[list[str]], label: str) -> str:
    for row in rows:
        for index, value in enumerate(row[:-1]):
            if _normalized(value).rstrip(":") == label:
                return row[index + 1]
    raise ValueError("invalid teaching plan")


def _assessment(row: list[str]) -> dict[str, object]:
    scheduled = datetime.strptime(row[3], "%d/%m/%Y %H:%M")
    return {
        "code": _required(row[0]),
        "kind": _required(row[1]),
        "title": _required(row[2]),
        "scheduled_at": scheduled.isoformat() + "-03:00",
        "location": _required(row[4]),
        "value": _decimal(row[5]),
        "weight": _decimal(row[6]),
    }


def _schedule_entry(row: list[str]) -> dict[str, object]:
    sequence = int(row[0])
    lessons = int(row[3])
    times = _TIME_RANGE.fullmatch(row[4])
    if not 1 <= sequence <= 1_000 or lessons not in {1, 2, 4} or times is None:
        raise ValueError("invalid teaching plan")
    return {
        "sequence": sequence,
        "date": datetime.strptime(row[1], "%d/%m/%Y").date().isoformat(),
        "weekday": _required(row[2]),
        "lesson_count": lessons,
        "starts_at": times[1],
        "ends_at": times[2],
        "kind": _required(row[5]),
        "subject": _required(row[6]),
    }


def _decimal(value: str) -> str:
    try:
        parsed = Decimal(value.replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError("invalid teaching plan") from None
    if parsed < 0 or parsed > 100_000:
        raise ValueError("invalid teaching plan")
    return f"{parsed:.2f}"


def _required(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > _MAX_TEXT:
        raise ValueError("invalid teaching plan")
    return normalized


def _normalized(value: str) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(folded.split())
