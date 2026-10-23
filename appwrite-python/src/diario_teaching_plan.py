"""Extract bounded structured facts from an official UFMG Diário teaching plan."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

_TERM = re.compile(r"(20[2-9][0-9])\s*[/.-]\s*([12])")
_COURSE = re.compile(r"\b([A-Z]{3}[0-9]{3})\b\s+(.{1,160})")
_TIME_RANGE = re.compile(r"([0-2][0-9]:[0-5][0-9])\s*-\s*([0-2][0-9]:[0-5][0-9])")
_MAX_ROWS = 1_000
_MAX_CELLS = 32
_MAX_TEXT = 500
_MAX_LOG_ROWS = 40
_MAX_LOG_ROW_TEXT = 300


class TeachingPlanParseError(ValueError):
    """A plan failed parsing, with bounded report diagnostics for operations."""

    def __init__(
        self,
        stage: str,
        *,
        rows: list[list[str]],
        assessment_total: int = 0,
        criteria_total: int = 0,
        schedule_total: int = 0,
    ) -> None:
        self.stage = stage
        self.diagnostics: dict[str, object] = {
            "parser_stage": stage,
            "row_count": len(rows),
            "nonempty_cell_count": sum(len(row) for row in rows),
            "max_row_cells": max((len(row) for row in rows), default=0),
            "assessment_total": assessment_total,
            "criteria_total": criteria_total,
            "schedule_total": schedule_total,
            "sample_rows": [
                " | ".join(row)[:_MAX_LOG_ROW_TEXT] for row in rows[:_MAX_LOG_ROWS]
            ],
        }
        super().__init__(f"invalid teaching plan at {stage}")


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
            if len(value) > _MAX_TEXT:
                raise ValueError("invalid teaching plan")
            # Jasper uses spacer cells to reproduce the PDF layout. They carry
            # no data and must not count toward the bounded semantic row.
            if value:
                if len(self._row) >= _MAX_CELLS:
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
        raise TeachingPlanParseError("document_bounds", rows=[])
    parser = _TableParser()
    try:
        parser.feed(markup)
    except ValueError:
        raise TeachingPlanParseError("html_layout", rows=parser.rows) from None
    rows = parser.rows
    try:
        term = _label_value(rows, "periodo")
        activity = _label_value(rows, "atividade")
        class_group = _label_value(rows, "turma")
    except ValueError:
        raise TeachingPlanParseError("identity_labels", rows=rows) from None
    term_match = _TERM.search(term)
    course_match = _COURSE.search(activity)
    if term_match is None or course_match is None or not class_group:
        raise TeachingPlanParseError("identity_values", rows=rows)

    assessments: list[dict[str, object]] = []
    undated_assessment_total = 0
    criteria: list[dict[str, str]] = []
    schedule: list[dict[str, object]] = []
    section: str | None = None
    try:
        for row in rows:
            normalized = [_normalized(cell) for cell in row]
            if _header_matches(
                normalized,
                ("cod", "tipo", "nome", "data/hora", "local", "valor", "peso"),
            ):
                section = "assessments"
                continue
            if _header_matches(normalized, ("descricao", "valor parcial")):
                section = "criteria"
                continue
            if _header_matches(
                normalized,
                ("aula", "data", "dia", "num aula", "horario", "tipo", "assunto"),
            ):
                section = "schedule"
                continue
            if section == "assessments" and len(row) == 7:
                assessments.append(_assessment(row))
            elif section == "criteria" and len(row) == 2:
                criteria.append(
                    {"description": _required(row[0]), "value": _decimal(row[1])}
                )
            elif section == "schedule" and len(row) == 7:
                schedule.append(_schedule_entry(row))

        if not assessments:
            assessments, undated_assessment_total = _parse_labeled_assessments(rows)
    except ValueError:
        raise TeachingPlanParseError(
            "section_values",
            rows=rows,
            assessment_total=len(assessments),
            criteria_total=len(criteria),
            schedule_total=len(schedule),
        ) from None

    if not assessments and not criteria and not schedule:
        raise TeachingPlanParseError(
            "required_sections",
            rows=rows,
            assessment_total=len(assessments),
            criteria_total=len(criteria),
            schedule_total=len(schedule),
        )
    return {
        "term": f"{term_match[1]}-{term_match[2]}",
        "course_code": course_match[1],
        "course_name": _required(course_match[2]),
        "class_group": _required(class_group),
        "assessments": assessments,
        "undated_assessment_total": undated_assessment_total,
        "criteria": criteria,
        "schedule": schedule,
        "source": "ufmg_diario",
        "confidence": "authoritative",
    }


def _label_value(rows: list[list[str]], label: str) -> str:
    for row in rows:
        for index, value in enumerate(row):
            normalized = _normalized(value)
            key, separator, inline_value = normalized.partition(":")
            if key == label:
                if separator and inline_value.strip():
                    return value.split(":", 1)[1].strip()
                if index + 1 < len(row):
                    return row[index + 1]
    raise ValueError("invalid teaching plan")


def _header_matches(values: list[str], expected: tuple[str, ...]) -> bool:
    if len(values) < len(expected):
        return False
    canonical = tuple(_header_token(value) for value in values[: len(expected)])
    return canonical == expected


def _header_token(value: str) -> str:
    token = value.rstrip(":.").replace(".", "")
    if token in {"cod avl", "codigo", "codigo avl"}:
        return "cod"
    if token in {
        "horas aula",
        "num aulas",
        "num aula",
        "numero aulas",
        "numero aula",
    }:
        return "num aula"
    return token


def _assessment(row: list[str]) -> dict[str, object]:
    scheduled = datetime.strptime(row[3], "%d/%m/%Y %H:%M")
    return {
        "code": _required(row[0]),
        "kind": _required(row[1]),
        "title": _required(row[2]),
        "scheduled_at": scheduled.isoformat() + "-03:00",
        "location": _optional(row[4]),
        "value": _decimal(row[5]),
        "weight": _decimal(row[6]),
    }


def _labeled_assessments(rows: list[list[str]]) -> list[dict[str, object]]:
    return _parse_labeled_assessments(rows)[0]


def _parse_labeled_assessments(
    rows: list[list[str]],
) -> tuple[list[dict[str, object]], int]:
    labels = ("cod avl", "cod", "tipo", "nome", "data/hora", "local", "valor", "peso")
    assessments: list[dict[str, object]] = []
    undated_total = 0
    pending: dict[str, str] = {}
    for row in rows:
        values = _row_labeled_values(row, labels)
        if "cod avl" in values or "cod" in values:
            if pending:
                _assessment_from_labels(pending)
                undated_total += 1
            pending = {"code": values.pop("cod avl", values.pop("cod", ""))}
        if pending:
            pending.update(values)
            if {"code", "tipo", "nome", "data/hora", "valor", "peso"} <= set(pending):
                assessment = _assessment_from_labels(pending)
                assert assessment is not None
                assessments.append(assessment)
                pending = {}
    if pending:
        _assessment_from_labels(pending)
        undated_total += 1
    return assessments, undated_total


def _row_labeled_values(row: list[str], labels: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for index, cell in enumerate(row):
        normalized = _normalized(cell)
        plain = normalized.replace(".", "")
        for label in labels:
            if _header_token(normalized) == label:
                if index + 1 < len(row):
                    candidate = row[index + 1]
                    if not any(
                        _header_token(_normalized(candidate)) == other for other in labels
                    ):
                        result[label] = candidate
                break
            prefix = f"{label}:"
            if plain.startswith(prefix) and plain[len(prefix) :].strip():
                result[label] = cell.split(":", 1)[1].strip()
                break
            prefix = f"{label} "
            if plain.startswith(prefix) and plain[len(prefix) :].strip():
                result[label] = cell[len(label) :].strip(" :.\t")
                break
    return result


def _assessment_from_labels(values: dict[str, str]) -> dict[str, object] | None:
    try:
        if not values.get("data/hora"):
            for key in ("code", "tipo", "nome", "valor", "peso"):
                _required(values[key])
            return None
        return _assessment(
            [
                values["code"],
                values["tipo"],
                values["nome"],
                values["data/hora"],
                values.get("local", ""),
                values["valor"],
                values["peso"],
            ]
        )
    except KeyError:
        raise ValueError("invalid teaching plan") from None


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


def _optional(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) > _MAX_TEXT:
        raise ValueError("invalid teaching plan")
    return normalized


def _normalized(value: str) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(folded.split())
