import pytest

from diario_teaching_plan import (
    TeachingPlanParseError,
    _decimal,
    _label_value,
    _labeled_assessments,
    _optional,
    _required,
    _row_labeled_values,
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
        "undated_assessment_total": 0,
        "criteria": [
            {"description": "Soma das notas das 3 melhores notas", "value": "99.00"},
            {"description": "Soma das notas das avaliações", "value": "1.00"},
        ],
        "schedule": [
            {
                "sequence": 1,
                "occurrence_key": "2026-08-05T20:55-22:35",
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
                "occurrence_key": "2026-08-10T19:00-20:40",
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
    except TeachingPlanParseError as error:
        assert error.stage == "identity_labels"
        assert error.diagnostics == {
            "parser_stage": "identity_labels",
            "row_count": 0,
            "nonempty_cell_count": 0,
            "max_row_cells": 0,
            "assessment_total": 0,
            "criteria_total": 0,
            "schedule_total": 0,
            "sample_rows": [],
        }
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
        _TableParser().feed("<table><tr>" + "<td>x</td>" * 33 + "</tr></table>")
    with pytest.raises(ValueError):
        _TableParser().feed("<table>" + "<tr><td>x</td></tr>" * 1001 + "</table>")


def test_parser_reports_the_html_layout_stage_with_the_rows_seen_so_far() -> None:
    markup = "<table><tr><td>visible</td></tr><tr>" + "<td>x</td>" * 33 + "</tr></table>"

    with pytest.raises(TeachingPlanParseError) as raised:
        parse_teaching_plan_html(markup)

    assert raised.value.stage == "html_layout"
    assert raised.value.diagnostics["row_count"] == 1
    assert raised.value.diagnostics["sample_rows"] == ["visible"]


def test_parser_reports_the_section_and_partial_totals_that_failed() -> None:
    markup = """
      <table>
        <tr><td>Período:</td><td>2026/2</td><td>Atividade:</td><td>MAT002 Cálculo II</td></tr>
        <tr><td>Turma:</td><td>T1</td></tr>
        <tr><th>Cód.</th><th>Tipo</th><th>Nome</th><th>Data/Hora</th>
          <th>Local</th><th>Valor</th><th>Peso</th></tr>
        <tr><td>AV1</td><td>PROVA</td><td>Prova inválida</td>
          <td>data inválida</td><td>Sala</td><td>10,00</td><td>1,00</td></tr>
      </table>
    """

    with pytest.raises(TeachingPlanParseError) as raised:
        parse_teaching_plan_html(markup)

    assert raised.value.stage == "section_values"
    assert raised.value.diagnostics["assessment_total"] == 0
    assert "Prova inválida" in " ".join(raised.value.diagnostics["sample_rows"])


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


def test_parses_jasper_layout_cells_and_observed_ufmg_labels() -> None:
    spacers = "<td></td>" * 40
    html = f"""
      <table>
        <tr>{spacers}<td>Período: 2026/2</td><td>Orientante:</td><td>MATEMÁTICA</td></tr>
        <tr>{spacers}<td>Atividade:</td><td>DIG MAT002 CÁLCULO DIFERENCIAL II</td></tr>
        <tr>{spacers}<td>Turma: T1</td></tr>
        <tr>{spacers}<td>Cód. Avl:</td><td>Tipo:</td><td>Nome:</td>
          <td>Data/Hora:</td><td>Local:</td><td>Valor:</td><td>Peso:</td></tr>
        <tr>{spacers}<td>AV1</td><td>PROVA</td><td>PRIMEIRA PROVA</td>
          <td>09/09/2026 20:50</td><td>Local</td><td>33,00</td><td>1,00</td></tr>
        <tr>{spacers}<td>Descrição</td><td>Valor Parcial</td></tr>
        <tr>{spacers}<td>Soma das avaliações</td><td>100,00</td></tr>
        <tr>{spacers}<td>Aula</td><td>Data</td><td>Dia</td><td>Num. Aula</td>
          <td>Horário</td><td>Tipo</td><td>Assunto</td></tr>
        <tr>{spacers}<td>1</td><td>05/08/2026</td><td>Qua</td><td>2</td>
          <td>20:55 - 22:35</td><td>Teórica</td><td>Integrais</td></tr>
      </table>
    """

    result = parse_teaching_plan_html(html)

    assert result["course_code"] == "MAT002"
    assert result["course_name"] == "CÁLCULO DIFERENCIAL II"
    assert result["class_group"] == "T1"
    assert len(result["assessments"]) == 1
    assert len(result["schedule"]) == 1


def test_parses_observed_jasper_label_value_assessments_with_blank_location() -> None:
    html = """
      <table>
        <tr><td>Período:</td><td>2026/2 Orientante: 1000003 MATEMÁTICA</td></tr>
        <tr><td>Atividade:</td><td>DIG MAT002 CÁLCULO DIFERENCIAL II</td></tr>
        <tr><td>Turma:</td><td>T1</td></tr>
        <tr><td>Avaliações</td></tr>
        <tr><td>Cód. Avl:</td><td>AV1</td><td>Tipo:</td><td>PROVA</td>
          <td>Nome:</td><td>PRIMEIRA PROVA</td></tr>
        <tr><td>Data/Hora:</td><td>09/09/2026 20:50</td><td>Local:</td>
          <td>Valor:</td><td>33,00</td><td>Peso:</td><td>1,00</td></tr>
        <tr><td>Descrição</td><td>Valor Parcial</td></tr>
        <tr><td>Soma das avaliações</td><td>100,00</td></tr>
        <tr><td>Aula</td><td>Data</td><td>Dia</td><td>Num. Aulas</td>
          <td>Horário</td><td>Tipo</td><td>Assunto</td></tr>
        <tr><td>1</td><td>05/08/2026</td><td>Qua</td><td>2</td>
          <td>20:55 - 22:35</td><td>Teórica</td><td>Integrais</td></tr>
      </table>
    """

    result = parse_teaching_plan_html(html)

    assert result["term"] == "2026-2"
    assert result["assessments"] == [
        {
            "code": "AV1",
            "kind": "PROVA",
            "title": "PRIMEIRA PROVA",
            "scheduled_at": "2026-09-09T20:50:00-03:00",
            "location": "",
            "value": "33.00",
            "weight": "1.00",
        }
    ]


def test_accepts_observed_plan_with_undated_assessments_and_horas_aula() -> None:
    html = """
      <table>
        <tr><td>Período:</td><td>2026/2</td><td>Ofertante:</td><td>ENGENHARIA ELÉTRICA</td></tr>
        <tr><td>Atividade:</td><td>DIG ELE065 ANALISE DE CIRCUITOS ELETRICOS II</td></tr>
        <tr><td>Turma:</td><td>TTEC</td></tr>
        <tr><td>Cód:</td><td>AV1</td><td>Tipo:</td><td>PROVA</td>
          <td>Nome:</td><td>Avaliação 1</td></tr>
        <tr><td>Data/Hora:</td><td>Local:</td><td>Sala de aula</td>
          <td>Valor:</td><td>35,00</td><td>Peso:</td><td>1,00</td></tr>
        <tr><td>Cód:</td><td>AV2</td><td>Tipo:</td><td>PROVA</td>
          <td>Nome:</td><td>Avaliação 2</td></tr>
        <tr><td>Data/Hora:</td><td>Local:</td><td>Sala de aula</td>
          <td>Valor:</td><td>35,00</td><td>Peso:</td><td>1,00</td></tr>
        <tr><td>Descrição</td><td>Valor Parcial</td></tr>
        <tr><td>Soma das avaliações</td><td>100,00</td></tr>
        <tr><td>Aula</td><td>Data</td><td>Dia</td><td>Horas Aula</td>
          <td>Horário</td><td>Tipo</td><td>Assunto</td></tr>
        <tr><td>1</td><td>07/08/2026</td><td>Sex</td><td>2</td>
          <td>19:00 - 20:40</td><td>Teórica</td><td>Introdução</td></tr>
      </table>
    """

    result = parse_teaching_plan_html(html)

    assert result["assessments"] == []
    assert result["undated_assessment_total"] == 2
    assert len(result["criteria"]) == 1
    assert len(result["schedule"]) == 1


def test_accepts_observed_plan_with_only_a_schedule() -> None:
    html = """
      <table>
        <tr><td>Período:</td><td>2026/2</td><td>Ofertante:</td><td>ENGENHARIA ELÉTRICA</td></tr>
        <tr><td>Atividade:</td><td>DIG ELE631 ANALISE E PROJETO ORIENTADOS A OBJETOS</td></tr>
        <tr><td>Turma:</td><td>TAPO</td></tr>
        <tr><td>Aula</td><td>Data</td><td>Dia</td><td>Horas Aula</td>
          <td>Horário</td><td>Tipo</td><td>Assunto</td></tr>
        <tr><td>1</td><td>04/08/2026</td><td>Ter</td><td>2</td>
          <td>19:00 - 20:40</td><td>Teórica</td><td>Acerto de matrícula</td></tr>
      </table>
    """

    result = parse_teaching_plan_html(html)

    assert result["assessments"] == []
    assert result["undated_assessment_total"] == 0
    assert result["criteria"] == []
    assert len(result["schedule"]) == 1


def test_labeled_assessment_rejects_incomplete_records() -> None:
    with pytest.raises(ValueError):
        _labeled_assessments([["Cód. Avl:", "AV1"], ["Cód. Avl:", "AV2"]])
    with pytest.raises(ValueError):
        _labeled_assessments([["Cód. Avl:", "AV1"]])


def test_labeled_cells_support_inline_and_terminal_labels() -> None:
    labels = ("cod avl", "tipo", "nome")
    assert _row_labeled_values(
        ["Cód. Avl: AV1", "Tipo PROVA", "Nome:"], labels
    ) == {"cod avl": "AV1", "tipo": "PROVA"}
    with pytest.raises(ValueError):
        _label_value([["Período:"]], "periodo")


def test_labeled_record_and_optional_values_remain_bounded() -> None:
    with pytest.raises(ValueError):
        _optional("x" * 501)


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


def test_schedule_entry_exposes_a_stable_occurrence_key() -> None:
    entry = _schedule_entry(
        ["7", "14/09/2026", "Seg", "2", "19:00 - 20:40", "Teórica", "Herança"]
    )

    assert entry["occurrence_key"] == "2026-09-14T19:00-20:40"


@pytest.mark.parametrize("value", ["não-numérico", "-1", "100001"])
def test_decimal_rejects_invalid_or_unbounded_values(value: str) -> None:
    with pytest.raises(ValueError):
        _decimal(value)


@pytest.mark.parametrize("value", ["", "x" * 501])
def test_required_rejects_empty_or_oversized_values(value: str) -> None:
    with pytest.raises(ValueError):
        _required(value)
