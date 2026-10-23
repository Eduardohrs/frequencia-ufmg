import pytest

from diario_teaching_plan import (
    _decimal,
    _required,
    _schedule_entry,
    _TableParser,
    parse_teaching_plan_html,
)


def test_parses_sanitized_real_diario_tables() -> None:
    html = """
      <html><body>
        <table>
          <tr><td>Período:</td><td>2026/2</td><td>Atividade:</td>
              <td>MAT002 CÁLCULO DIFERENCIAL E INTEGRAL II</td></tr>
          <tr><td>Turma:</td><td>T1</td></tr>
        </table>
        <h2>Avaliações</h2>
        <table>
          <tr><th>Cód.</th><th>Tipo</th><th>Nome</th><th>Data/Hora</th>
              <th>Local</th><th>Valor</th><th>Peso</th></tr>
          <tr><td>AV1</td><td>PROVA</td><td>PRIMEIRA PROVA</td>
              <td>09/09/2026 20:50</td><td>Local</td><td>33,00</td><td>1,00</td></tr>
          <tr><td>AV2</td><td>PROVA</td><td>SEGUNDA PROVA</td>
              <td>19/10/2026 20:50</td><td>Local</td><td>33,00</td><td>1,00</td></tr>
        </table>
        <h2>Critérios para Cálculo de Nota Final</h2>
        <table>
          <tr><th>Descrição</th><th>Valor Parcial</th></tr>
          <tr><td>Soma das notas das 3 melhores notas</td><td>99,00</td></tr>
          <tr><td>Soma das notas das avaliações</td><td>1,00</td></tr>
        </table>
        <h2>Cronograma</h2>
        <table>
          <tr><th>Aula</th><th>Data</th><th>Dia</th><th>Num. Aulas</th>
              <th>Horário</th><th>Tipo</th><th>Assunto</th></tr>
          <tr><td>1</td><td>05/08/2026</td><td>Qua</td><td>2</td>
              <td>20:55 - 22:35</td><td>Teórica</td><td>Integrais Duplas: definição</td></tr>
          <tr><td>2</td><td>10/08/2026</td><td>Seg</td><td>2</td>
              <td>19:00 - 20:40</td><td>Teórica</td><td>Teorema de Fubini</td></tr>
        </table>
      </body></html>
    """

    result = parse_teaching_plan_html(html)

    assert result == {
        "term": "2026-2",
        "course_code": "MAT002",
        "course_name": "CÁLCULO DIFERENCIAL E INTEGRAL II",
        "class_group": "T1",
        "assessments": [
            {
                "code": "AV1",
                "kind": "PROVA",
                "title": "PRIMEIRA PROVA",
                "scheduled_at": "2026-09-09T20:50:00-03:00",
                "location": "Local",
                "value": "33.00",
                "weight": "1.00",
            },
            {
                "code": "AV2",
                "kind": "PROVA",
                "title": "SEGUNDA PROVA",
                "scheduled_at": "2026-10-19T20:50:00-03:00",
                "location": "Local",
                "value": "33.00",
                "weight": "1.00",
            },
        ],
        "criteria": [
            {"description": "Soma das notas das 3 melhores notas", "value": "99.00"},
            {"description": "Soma das notas das avaliações", "value": "1.00"},
        ],
        "schedule": [
            {
                "sequence": 1,
                "date": "2026-08-05",
                "weekday": "Qua",
                "lesson_count": 2,
                "starts_at": "20:55",
                "ends_at": "22:35",
                "kind": "Teórica",
                "subject": "Integrais Duplas: definição",
            },
            {
                "sequence": 2,
                "date": "2026-08-10",
                "weekday": "Seg",
                "lesson_count": 2,
                "starts_at": "19:00",
                "ends_at": "20:40",
                "kind": "Teórica",
                "subject": "Teorema de Fubini",
            },
        ],
        "source": "ufmg_diario",
        "confidence": "authoritative",
    }


def test_rejects_a_document_without_all_required_sections() -> None:
    try:
        parse_teaching_plan_html("<h2>Avaliações</h2><table></table>")
    except ValueError as error:
        assert str(error) == "invalid teaching plan"
    else:
        raise AssertionError("invalid plan accepted")


def test_rejects_empty_or_oversized_documents() -> None:
    with pytest.raises(ValueError):
        parse_teaching_plan_html("")
    with pytest.raises(ValueError):
        parse_teaching_plan_html("x" * (20 * 1_048_576 + 1))


def test_table_parser_enforces_cell_and_row_bounds() -> None:
    parser = _TableParser()
    parser.feed("<table><tr></tr></table>")
    assert parser.rows == []
    with pytest.raises(ValueError):
        _TableParser().feed(f"<table><tr><td>{'x' * 501}</td></tr></table>")
    with pytest.raises(ValueError):
        _TableParser().feed("<table><tr>" + "<td>x</td>" * 13 + "</tr></table>")
    with pytest.raises(ValueError):
        _TableParser().feed("<table>" + "<tr><td>x</td></tr>" * 1001 + "</table>")


def test_rejects_invalid_identity_and_missing_sections_after_identity() -> None:
    invalid_identity = """
      <table><tr><td>Período:</td><td>inválido</td>
      <td>Atividade:</td><td>sem código</td></tr>
      <tr><td>Turma:</td><td>T1</td></tr></table>
    """
    with pytest.raises(ValueError):
        parse_teaching_plan_html(invalid_identity)

    identity_only = """
      <table><tr><td>Período:</td><td>2026/2</td>
      <td>Atividade:</td><td>MAT002 Cálculo II</td></tr>
      <tr><td>Turma:</td><td>T1</td></tr></table>
    """
    with pytest.raises(ValueError):
        parse_teaching_plan_html(identity_only)


@pytest.mark.parametrize(
    "row",
    [
        ["0", "05/08/2026", "Qua", "2", "20:55 - 22:35", "Teórica", "X"],
        ["1", "05/08/2026", "Qua", "3", "20:55 - 22:35", "Teórica", "X"],
        ["1", "05/08/2026", "Qua", "2", "inválido", "Teórica", "X"],
    ],
)
def test_schedule_rejects_invalid_identity(row: list[str]) -> None:
    with pytest.raises(ValueError):
        _schedule_entry(row)


@pytest.mark.parametrize("value", ["não-numérico", "-1", "100001"])
def test_decimal_rejects_invalid_or_unbounded_values(value: str) -> None:
    with pytest.raises(ValueError):
        _decimal(value)


@pytest.mark.parametrize("value", ["", "x" * 501])
def test_required_rejects_empty_or_oversized_values(value: str) -> None:
    with pytest.raises(ValueError):
        _required(value)
