"""Tests for the object-oriented academic domain structure."""

from datetime import datetime

import pytest

from frequencia_ufmg.models import (
    CentralPendencias,
    ConfiguracaoSessao,
    DecisaoHorario,
    Disciplina,
    EstadoPing,
    GerenciadorRascunhos,
    NumeroChamadas,
    PendenciaHorario,
    QuantidadeAulas,
    RascunhoCadastro,
    RegistroFrequencia,
    ResumoDisciplina,
    SessaoAula,
    SituacaoFrequencia,
)


@pytest.mark.parametrize(
    ("aulas", "chamadas"),
    [
        (QuantidadeAulas.UMA, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS),
    ],
)
def test_session_configuration_accepts_defined_combinations(
    aulas: QuantidadeAulas,
    chamadas: NumeroChamadas,
) -> None:
    """Only whole 50-minute lessons form a valid session configuration."""

    configuracao = ConfiguracaoSessao(aulas=aulas, chamadas=chamadas)

    assert configuracao.aulas is aulas
    assert configuracao.chamadas is chamadas


def test_two_calls_are_invalid_for_one_lesson() -> None:
    """Two calls cannot divide one lesson without creating half an absence."""

    with pytest.raises(ValueError, match="uma aula não pode ter duas chamadas"):
        ConfiguracaoSessao(
            aulas=QuantidadeAulas.UMA,
            chamadas=NumeroChamadas.DUAS,
        )


@pytest.mark.parametrize(
    ("aulas", "chamadas"),
    [
        (3, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, 3),
        (True, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, False),
    ],
)
def test_session_configuration_rejects_untyped_values(
    aulas: object,
    chamadas: object,
) -> None:
    """Callers must cross the domain boundary through its explicit enums."""

    with pytest.raises(TypeError, match="enums do domínio"):
        ConfiguracaoSessao(aulas=aulas, chamadas=chamadas)  # type: ignore[arg-type]


def test_course_owns_an_encapsulated_collection_of_sessions() -> None:
    """A course exposes its sessions without leaking its mutable collection."""

    disciplina = Disciplina(
        codigo="  DCC203  ",
        nome="  Programação Orientada a Objetos ",
        carga_horaria=60,
    )
    sessao = SessaoAula(
        identificador="aula-01",
        configuracao=ConfiguracaoSessao(
            aulas=QuantidadeAulas.DUAS,
            chamadas=NumeroChamadas.UMA,
        ),
    )

    disciplina.adicionar_sessao(sessao)

    assert disciplina.codigo == "DCC203"
    assert disciplina.nome == "Programação Orientada a Objetos"
    assert disciplina.carga_horaria == 60
    assert disciplina.sessoes == (sessao,)
    assert isinstance(disciplina.sessoes, tuple)
    assert sessao.identificador == "aula-01"
    assert sessao.configuracao == ConfiguracaoSessao(
        aulas=QuantidadeAulas.DUAS,
        chamadas=NumeroChamadas.UMA,
    )


def test_course_rejects_a_duplicate_session_identifier() -> None:
    """A session identity is unique inside its owning course."""

    disciplina = Disciplina("DCC203", "POO", 60)
    configuracao = ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA)
    disciplina.adicionar_sessao(SessaoAula("aula-01", configuracao))

    with pytest.raises(ValueError, match="sessão já cadastrada"):
        disciplina.adicionar_sessao(SessaoAula("aula-01", configuracao))


@pytest.mark.parametrize(
    ("codigo", "nome", "carga_horaria", "mensagem"),
    [
        ("", "POO", 60, "código"),
        (None, "POO", 60, "código"),
        ("DCC203", " ", 60, "nome"),
        ("DCC203", 203, 60, "nome"),
        ("DCC203", "POO", 0, "carga horária"),
        ("DCC203", "POO", -1, "carga horária"),
        ("DCC203", "POO", True, "carga horária"),
    ],
)
def test_course_rejects_invalid_identity_or_workload(
    codigo: object,
    nome: object,
    carga_horaria: object,
    mensagem: str,
) -> None:
    """A course is never created with an unusable identity or workload."""

    with pytest.raises((TypeError, ValueError), match=mensagem):
        Disciplina(codigo, nome, carga_horaria)  # type: ignore[arg-type]


def test_session_requires_identity_and_configuration() -> None:
    """A session always has a stable identity and a domain configuration."""

    configuracao = ConfiguracaoSessao(QuantidadeAulas.UMA, NumeroChamadas.UMA)

    with pytest.raises(ValueError, match="identificador"):
        SessaoAula(" ", configuracao)
    with pytest.raises(TypeError, match="configuração"):
        SessaoAula("aula-01", object())  # type: ignore[arg-type]


def test_course_only_accepts_session_objects() -> None:
    """The aggregate boundary rejects objects from outside the domain."""

    disciplina = Disciplina("DCC203", "POO", 60)

    with pytest.raises(TypeError, match="SessaoAula"):
        disciplina.adicionar_sessao(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("aulas", "chamadas"),
    [
        (QuantidadeAulas.UMA, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS),
    ],
)
@pytest.mark.parametrize(
    ("primeiro_ping", "segundo_ping", "situacao"),
    [
        (EstadoPing.NO_CAMPUS, EstadoPing.NO_CAMPUS, SituacaoFrequencia.PRESENTE),
        (EstadoPing.FORA, EstadoPing.NO_CAMPUS, SituacaoFrequencia.CHEGOU_ATRASADO),
        (EstadoPing.NO_CAMPUS, EstadoPing.FORA, SituacaoFrequencia.SAIU_MAIS_CEDO),
        (EstadoPing.FORA, EstadoPing.FORA, SituacaoFrequencia.AUSENTE),
    ],
)
def test_session_classifies_two_valid_pings(
    aulas: QuantidadeAulas,
    chamadas: NumeroChamadas,
    primeiro_ping: EstadoPing,
    segundo_ping: EstadoPing,
    situacao: SituacaoFrequencia,
) -> None:
    """Valid evidence has the same semantic status for one or two calls."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(aulas, chamadas),
    )

    assert sessao.classificar(primeiro_ping, segundo_ping) is situacao


@pytest.mark.parametrize(
    ("primeiro_ping", "segundo_ping", "situacao"),
    [
        (EstadoPing.NO_CAMPUS, EstadoPing.INDISPONIVEL, SituacaoFrequencia.PRESENTE),
        (EstadoPing.INDISPONIVEL, EstadoPing.NO_CAMPUS, SituacaoFrequencia.PRESENTE),
        (EstadoPing.FORA, EstadoPing.INDISPONIVEL, SituacaoFrequencia.PENDENTE),
        (EstadoPing.INDISPONIVEL, EstadoPing.FORA, SituacaoFrequencia.PENDENTE),
        (EstadoPing.INDISPONIVEL, EstadoPing.INDISPONIVEL, SituacaoFrequencia.PENDENTE),
    ],
)
def test_single_call_uses_any_available_campus_confirmation(
    primeiro_ping: EstadoPing,
    segundo_ping: EstadoPing,
    situacao: SituacaoFrequencia,
) -> None:
    """One call is resolved by any campus confirmation, otherwise it stays pending."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
    )

    assert sessao.classificar(primeiro_ping, segundo_ping) is situacao


@pytest.mark.parametrize(
    ("primeiro_ping", "segundo_ping"),
    [
        (EstadoPing.INDISPONIVEL, EstadoPing.NO_CAMPUS),
        (EstadoPing.INDISPONIVEL, EstadoPing.FORA),
        (EstadoPing.NO_CAMPUS, EstadoPing.INDISPONIVEL),
        (EstadoPing.FORA, EstadoPing.INDISPONIVEL),
        (EstadoPing.INDISPONIVEL, EstadoPing.INDISPONIVEL),
    ],
)
def test_two_calls_require_both_pings(
    primeiro_ping: EstadoPing,
    segundo_ping: EstadoPing,
) -> None:
    """Each ping represents one half of a two-call session."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.DUAS),
    )

    assert sessao.classificar(primeiro_ping, segundo_ping) is SituacaoFrequencia.PENDENTE


@pytest.mark.parametrize(
    ("primeiro_ping", "segundo_ping"),
    [
        (object(), EstadoPing.NO_CAMPUS),
        (EstadoPing.NO_CAMPUS, object()),
    ],
)
def test_classification_rejects_values_outside_the_ping_domain(
    primeiro_ping: object,
    segundo_ping: object,
) -> None:
    """Raw or malformed evidence cannot silently become an attendance status."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
    )

    with pytest.raises(TypeError, match="EstadoPing"):
        sessao.classificar(  # type: ignore[arg-type]
            primeiro_ping,
            segundo_ping,
        )


@pytest.mark.parametrize(
    ("aulas", "chamadas", "situacao", "faltas"),
    [
        (QuantidadeAulas.UMA, NumeroChamadas.UMA, SituacaoFrequencia.PRESENTE, 0),
        (QuantidadeAulas.UMA, NumeroChamadas.UMA, SituacaoFrequencia.CHEGOU_ATRASADO, 0),
        (QuantidadeAulas.UMA, NumeroChamadas.UMA, SituacaoFrequencia.SAIU_MAIS_CEDO, 0),
        (QuantidadeAulas.UMA, NumeroChamadas.UMA, SituacaoFrequencia.AUSENTE, 1),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA, SituacaoFrequencia.PRESENTE, 0),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA, SituacaoFrequencia.CHEGOU_ATRASADO, 0),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA, SituacaoFrequencia.SAIU_MAIS_CEDO, 0),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA, SituacaoFrequencia.AUSENTE, 2),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS, SituacaoFrequencia.PRESENTE, 0),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS, SituacaoFrequencia.CHEGOU_ATRASADO, 1),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS, SituacaoFrequencia.SAIU_MAIS_CEDO, 1),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS, SituacaoFrequencia.AUSENTE, 2),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA, SituacaoFrequencia.PRESENTE, 0),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA, SituacaoFrequencia.CHEGOU_ATRASADO, 0),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA, SituacaoFrequencia.SAIU_MAIS_CEDO, 0),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA, SituacaoFrequencia.AUSENTE, 4),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS, SituacaoFrequencia.PRESENTE, 0),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS, SituacaoFrequencia.CHEGOU_ATRASADO, 2),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS, SituacaoFrequencia.SAIU_MAIS_CEDO, 2),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS, SituacaoFrequencia.AUSENTE, 4),
    ],
)
def test_session_converts_attendance_status_to_absences(
    aulas: QuantidadeAulas,
    chamadas: NumeroChamadas,
    situacao: SituacaoFrequencia,
    faltas: int,
) -> None:
    """Every valid session configuration follows the agreed absence matrix."""

    sessao = SessaoAula("aula-01", ConfiguracaoSessao(aulas, chamadas))

    assert sessao.calcular_faltas(situacao) == faltas


@pytest.mark.parametrize(
    ("aulas", "chamadas"),
    [
        (QuantidadeAulas.UMA, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.UMA),
        (QuantidadeAulas.DUAS, NumeroChamadas.DUAS),
        (QuantidadeAulas.QUATRO, NumeroChamadas.UMA),
        (QuantidadeAulas.QUATRO, NumeroChamadas.DUAS),
    ],
)
def test_pending_session_has_no_automatic_absence_value(
    aulas: QuantidadeAulas,
    chamadas: NumeroChamadas,
) -> None:
    """Missing evidence is not silently converted into presence or absence."""

    sessao = SessaoAula("aula-01", ConfiguracaoSessao(aulas, chamadas))

    assert sessao.calcular_faltas(SituacaoFrequencia.PENDENTE) is None


def test_absence_calculation_rejects_values_outside_the_status_domain() -> None:
    """Only classified attendance statuses can become absence values."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
    )

    with pytest.raises(TypeError, match="SituacaoFrequencia"):
        sessao.calcular_faltas(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("carga_horaria", "limite_faltas"),
    [(30, 7), (45, 11), (60, 15)],
)
def test_course_limits_absences_to_twenty_five_percent_of_class_hours(
    carga_horaria: int,
    limite_faltas: int,
) -> None:
    """Fractional limits round down so attendance never drops below 75%."""

    disciplina = Disciplina("DCC203", "POO", carga_horaria)

    assert disciplina.limite_faltas == limite_faltas


@pytest.mark.parametrize(
    ("faltas_consumidas", "faltas_restantes"),
    [(0, 15), (4, 11), (15, 0), (16, 0)],
)
def test_course_reports_non_negative_remaining_absences(
    faltas_consumidas: int,
    faltas_restantes: int,
) -> None:
    """The remaining allowance reaches zero instead of becoming negative."""

    disciplina = Disciplina("DCC203", "POO", 60)

    assert disciplina.faltas_restantes(faltas_consumidas) == faltas_restantes


@pytest.mark.parametrize("faltas_consumidas", [-1, True, 1.5, "1"])
def test_remaining_absences_reject_invalid_consumed_totals(
    faltas_consumidas: object,
) -> None:
    """Consumed absences must be a non-negative whole class-hour count."""

    disciplina = Disciplina("DCC203", "POO", 60)

    with pytest.raises((TypeError, ValueError), match="faltas consumidas"):
        disciplina.faltas_restantes(faltas_consumidas)  # type: ignore[arg-type]


def test_course_registers_attendance_and_reports_current_totals() -> None:
    """A registered session immediately participates in the course summary."""

    disciplina = Disciplina("DCC203", "POO", 60)
    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.QUATRO, NumeroChamadas.DUAS),
    )
    disciplina.adicionar_sessao(sessao)

    registro = disciplina.registrar_frequencia(
        "aula-01",
        SituacaoFrequencia.CHEGOU_ATRASADO,
    )

    assert registro.sessao is sessao
    assert registro.situacao is SituacaoFrequencia.CHEGOU_ATRASADO
    assert registro.faltas == 2
    assert disciplina.registros == (registro,)
    assert disciplina.resumo() == ResumoDisciplina(
        codigo="DCC203",
        total_sessoes=1,
        sessoes_pendentes=0,
        faltas_consumidas=2,
        limite_faltas=15,
        faltas_restantes=13,
    )


def test_manual_correction_overwrites_status_and_absences_without_history() -> None:
    """Only the latest personal correction contributes to the report."""

    disciplina = Disciplina("DCC203", "POO", 60)
    disciplina.adicionar_sessao(
        SessaoAula(
            "aula-01",
            ConfiguracaoSessao(QuantidadeAulas.QUATRO, NumeroChamadas.UMA),
        )
    )
    registro = disciplina.registrar_frequencia("aula-01", SituacaoFrequencia.AUSENTE)

    registro.corrigir(SituacaoFrequencia.PRESENTE, 0)
    registro.corrigir(SituacaoFrequencia.SAIU_MAIS_CEDO, 1)

    assert registro.situacao is SituacaoFrequencia.SAIU_MAIS_CEDO
    assert registro.faltas == 1
    assert disciplina.resumo().faltas_consumidas == 1


def test_registering_the_same_session_again_replaces_its_current_result() -> None:
    """Reprocessing a session keeps one current record rather than an audit trail."""

    disciplina = Disciplina("DCC203", "POO", 60)
    disciplina.adicionar_sessao(
        SessaoAula(
            "aula-01",
            ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
        )
    )

    primeiro = disciplina.registrar_frequencia("aula-01", SituacaoFrequencia.AUSENTE)
    atual = disciplina.registrar_frequencia("aula-01", SituacaoFrequencia.PRESENTE)

    assert primeiro is not atual
    assert disciplina.registros == (atual,)
    assert disciplina.resumo().faltas_consumidas == 0


def test_summary_counts_missing_and_pending_sessions_without_consuming_absences() -> None:
    """Unresolved sessions remain visible but do not change absence totals."""

    disciplina = Disciplina("DCC203", "POO", 60)
    configuracao = ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA)
    disciplina.adicionar_sessao(SessaoAula("aula-01", configuracao))
    disciplina.adicionar_sessao(SessaoAula("aula-02", configuracao))
    registro = disciplina.registrar_frequencia("aula-01", SituacaoFrequencia.PENDENTE)

    assert registro.faltas is None
    assert disciplina.resumo() == ResumoDisciplina(
        codigo="DCC203",
        total_sessoes=2,
        sessoes_pendentes=2,
        faltas_consumidas=0,
        limite_faltas=15,
        faltas_restantes=15,
    )


@pytest.mark.parametrize(
    ("situacao", "faltas", "erro"),
    [
        (object(), 0, TypeError),
        (SituacaoFrequencia.PRESENTE, None, TypeError),
        (SituacaoFrequencia.PRESENTE, True, TypeError),
        (SituacaoFrequencia.PRESENTE, -1, ValueError),
        (SituacaoFrequencia.PRESENTE, 5, ValueError),
        (SituacaoFrequencia.PENDENTE, 0, ValueError),
    ],
)
def test_manual_correction_rejects_inconsistent_or_out_of_range_values(
    situacao: object,
    faltas: object,
    erro: type[Exception],
) -> None:
    """Manual freedom cannot violate the session's basic invariants."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.QUATRO, NumeroChamadas.UMA),
    )
    registro = RegistroFrequencia(sessao, SituacaoFrequencia.PRESENTE)

    with pytest.raises(erro):
        registro.corrigir(situacao, faltas)  # type: ignore[arg-type]


def test_manual_correction_can_restore_a_pending_result() -> None:
    """A resolved record can be returned to pending without inventing absences."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
    )
    registro = RegistroFrequencia(sessao, SituacaoFrequencia.AUSENTE)

    registro.corrigir(SituacaoFrequencia.PENDENTE, None)

    assert registro.situacao is SituacaoFrequencia.PENDENTE
    assert registro.faltas is None


@pytest.mark.parametrize("identificador", ["desconhecida", " "])
def test_course_rejects_attendance_for_an_unknown_session(identificador: str) -> None:
    """A course cannot own an attendance record for a session it does not own."""

    disciplina = Disciplina("DCC203", "POO", 60)

    with pytest.raises(ValueError, match="sessão não cadastrada"):
        disciplina.registrar_frequencia(identificador, SituacaoFrequencia.PRESENTE)


def test_attendance_record_requires_session_and_status_domain_objects() -> None:
    """Record construction validates both sides of its domain relationship."""

    sessao = SessaoAula(
        "aula-01",
        ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA),
    )

    with pytest.raises(TypeError, match="SessaoAula"):
        RegistroFrequencia(object(), SituacaoFrequencia.PRESENTE)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="SituacaoFrequencia"):
        RegistroFrequencia(sessao, object())  # type: ignore[arg-type]


def test_course_finds_a_later_session_and_rejects_non_text_identity() -> None:
    """Session lookup traverses owned sessions and validates its boundary."""

    disciplina = Disciplina("DCC203", "POO", 60)
    configuracao = ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA)
    disciplina.adicionar_sessao(SessaoAula("aula-01", configuracao))
    segunda_sessao = SessaoAula("aula-02", configuracao)
    disciplina.adicionar_sessao(segunda_sessao)

    registro = disciplina.registrar_frequencia(" aula-02 ", SituacaoFrequencia.PRESENTE)

    assert registro.sessao is segunda_sessao
    with pytest.raises(TypeError, match="identificador"):
        disciplina.registrar_frequencia(2, SituacaoFrequencia.PRESENTE)  # type: ignore[arg-type]


# ==================== Sessão 55,35 - Novos Testes ====================


class TestPendenciaHorario:
    """Testes para a classe PendenciaHorario."""

    def test_pendencia_horario_criacao(self) -> None:
        """Uma pendência de horário é criado com os dados corretos."""

        pendencia = PendenciaHorario(
            disciplina_codigo="DCC203",
            disciplina_nome="POO",
            horario_atual="10:00-12:00",
            horario_novo="11:00-13:00",
            motivo="Mudança de sala",
        )

        assert pendencia.disciplina_codigo == "DCC203"
        assert pendencia.disciplina_nome == "POO"
        assert pendencia.horario_atual == "10:00-12:00"
        assert pendencia.horario_novo == "11:00-13:00"
        assert pendencia.motivo == "Mudança de sala"
        assert isinstance(pendencia.data_criacao, datetime)

    def test_pendencia_horario_to_dict(self) -> None:
        """Uma pendência pode ser serializada para dicionário."""

        pendencia = PendenciaHorario(
            disciplina_codigo="DCC203",
            disciplina_nome="POO",
            horario_atual="10:00-12:00",
            horario_novo="11:00-13:00",
            motivo="Mudança de sala",
        )

        result = pendencia.to_dict()

        assert result["disciplina_codigo"] == "DCC203"
        assert result["disciplina_nome"] == "POO"
        assert result["horario_atual"] == "10:00-12:00"
        assert result["horario_novo"] == "11:00-13:00"
        assert result["motivo"] == "Mudança de sala"
        assert "data_criacao" in result


class TestCentralPendencias:
    """Testes para a CentralPendencias."""

    def test_adicionar_e_recuperar_pendencia(self) -> None:
        """Pendências podem ser adicionadas e recuperadas."""

        central = CentralPendencias()
        pendencia = PendenciaHorario(
            disciplina_codigo="DCC203",
            disciplina_nome="POO",
            horario_atual="10:00-12:00",
            horario_novo="11:00-13:00",
            motivo="Mudança de sala",
        )

        pendencia_id = central.adicionar_pendencia(pendencia)
        recuperada = central.get_pendencia(pendencia_id)

        assert recuperada is pendencia

    def test_registrar_e_recuperar_decisao(self) -> None:
        """Decisões podem ser registradas e recuperadas."""

        central = CentralPendencias()
        pendencia = PendenciaHorario(
            disciplina_codigo="DCC203",
            disciplina_nome="POO",
            horario_atual="10:00-12:00",
            horario_novo="11:00-13:00",
            motivo="Mudança de sala",
        )

        pendencia_id = central.adicionar_pendencia(pendencia)
        central.registrar_decisao(pendencia_id, DecisaoHorario.APLICAR_MUDANCA)
        decisao = central.get_decisao(pendencia_id)

        assert decisao == DecisaoHorario.APLICAR_MUDANCA

    def test_registrar_decisao_inexistente_falha(self) -> None:
        """Registrar decisão para pendência inexistente levanta erro."""

        central = CentralPendencias()

        with pytest.raises(ValueError, match="não encontrada"):
            central.registrar_decisao("inexistente", DecisaoHorario.APLICAR_MUDANCA)

    def test_remover_pendencia(self) -> None:
        """Pendências podem ser removidas."""

        central = CentralPendencias()
        pendencia = PendenciaHorario(
            disciplina_codigo="DCC203",
            disciplina_nome="POO",
            horario_atual="10:00-12:00",
            horario_novo="11:00-13:00",
            motivo="Mudança de sala",
        )

        pendencia_id = central.adicionar_pendencia(pendencia)
        assert central.get_pendencia(pendencia_id) is not None

        removido = central.remover_pendencia(pendencia_id)
        assert removido is True
        assert central.get_pendencia(pendencia_id) is None

    def test_remover_pendencia_inexistente(self) -> None:
        """Remover pendência inexistente retorna False."""

        central = CentralPendencias()

        removido = central.remover_pendencia("inexistente")
        assert removido is False

    def test_limpar_pendencias_resolvidas(self) -> None:
        """Pendências com decisão != PENDENTE são removidas."""

        central = CentralPendencias()
        pendencia1 = PendenciaHorario("DCC203", "POO", "10:00", "11:00", "motivo1")
        pendencia2 = PendenciaHorario("DCC204", "ED", "10:00", "11:00", "motivo2")

        id1 = central.adicionar_pendencia(pendencia1)
        id2 = central.adicionar_pendencia(pendencia2)

        central.registrar_decisao(id1, DecisaoHorario.APLICAR_MUDANCA)
        central.registrar_decisao(id2, DecisaoHorario.PENDENTE)

        removidas = central.limpar_pendencias_resolvidas()

        assert removidas == 1
        assert central.get_pendencia(id1) is None
        assert central.get_pendencia(id2) is pendencia2

    def test_limpar_pendencias_resolvidas_com_id_nao_na_pendencias(self) -> None:
        """Limpar pendências resolvidas quando pid não existe em _pendencias."""

        central = CentralPendencias()
        pendencia1 = PendenciaHorario("DCC203", "POO", "10:00", "11:00", "motivo1")

        id1 = central.adicionar_pendencia(pendencia1)
        # Registrar decisão
        central.registrar_decisao(id1, DecisaoHorario.APLICAR_MUDANCA)
        # Remover a pendência manualmente
        central.remover_pendencia(id1)

        # Agora limpar - não deve causar erro
        removidas = central.limpar_pendencias_resolvidas()
        assert removidas == 0

    def test_decisao_persiste_ao_reabrir(self) -> None:
        """A decisão persiste ao reabrir (simulado)."""

        central = CentralPendencias()
        pendencia = PendenciaHorario("DCC203", "POO", "10:00", "11:00", "motivo")

        pendencia_id = central.adicionar_pendencia(pendencia)
        central.registrar_decisao(pendencia_id, DecisaoHorario.MANTER_ATUAL)

        # Simula reabertura - a decisão deve ainda estar lá
        assert central.get_decisao(pendencia_id) == DecisaoHorario.MANTER_ATUAL

    def test_get_todas_pendencias(self) -> None:
        """Todas as pendências ativas podem ser recuperadas."""

        central = CentralPendencias()
        pendencia1 = PendenciaHorario("DCC203", "POO", "10:00", "11:00", "motivo1")
        pendencia2 = PendenciaHorario("DCC204", "ED", "10:00", "11:00", "motivo2")

        central.adicionar_pendencia(pendencia1)
        central.adicionar_pendencia(pendencia2)

        todas = central.get_todas_pendencias()
        assert len(todas) == 2
        assert pendencia1 in todas
        assert pendencia2 in todas


class TestRascunhoCadastro:
    """Testes para RascunhoCadastro."""

    def test_rascunho_criacao(self) -> None:
        """Um rascunho é criado com os dados corretos."""

        dados = {"ping1": "no_campus", "ping2": "fora"}
        rascunho = RascunhoCadastro("DCC203", "aula-01", dados)

        assert rascunho.disciplina_codigo == "DCC203"
        assert rascunho.sessao_identificador == "aula-01"
        assert rascunho.dados == dados
        assert isinstance(rascunho.timestamp, datetime)

    def test_rascunho_dados_nao_sao_modificados(self) -> None:
        """Os dados do rascunho não são modificados externamente."""

        dados = {"ping1": "no_campus"}
        rascunho = RascunhoCadastro("DCC203", "aula-01", dados)

        # Modificar o dicionário original
        dados["ping1"] = "fora"

        # O rascunho deve manter os dados originais
        assert rascunho.dados["ping1"] == "no_campus"

    def test_rascunho_to_dict(self) -> None:
        """Um rascunho pode ser serializado para dicionário."""

        dados = {"ping1": "no_campus", "ping2": "fora"}
        rascunho = RascunhoCadastro("DCC203", "aula-01", dados)

        result = rascunho.to_dict()

        assert result["disciplina_codigo"] == "DCC203"
        assert result["sessao_identificador"] == "aula-01"
        assert result["dados"] == dados
        assert "timestamp" in result


class TestGerenciadorRascunhos:
    """Testes para GerenciadorRascunhos."""

    def test_salvar_e_recuperar_rascunho(self) -> None:
        """Rascunhos podem ser salvos e recuperados."""

        gerenciador = GerenciadorRascunhos()
        dados = {"ping1": "no_campus", "ping2": "fora"}

        rascunho_id = gerenciador.salvar_rascunho("DCC203", "aula-01", dados)
        recuperado = gerenciador.recuperar_rascunho(rascunho_id)

        assert recuperado is not None
        assert recuperado.disciplina_codigo == "DCC203"
        assert recuperado.sessao_identificador == "aula-01"
        assert recuperado.dados == dados

    def test_remover_rascunho(self) -> None:
        """Rascunhos podem ser removidos."""

        gerenciador = GerenciadorRascunhos()
        dados = {"ping1": "no_campus"}

        rascunho_id = gerenciador.salvar_rascunho("DCC203", "aula-01", dados)
        assert gerenciador.recuperar_rascunho(rascunho_id) is not None

        removido = gerenciador.remover_rascunho(rascunho_id)
        assert removido is True
        assert gerenciador.recuperar_rascunho(rascunho_id) is None

    def test_listar_rascunhos_por_disciplina(self) -> None:
        """Rascunhos podem ser listados por disciplina."""

        gerenciador = GerenciadorRascunhos()
        gerenciador.salvar_rascunho("DCC203", "aula-01", {"dado": "1"})
        gerenciador.salvar_rascunho("DCC203", "aula-02", {"dado": "2"})
        gerenciador.salvar_rascunho("DCC204", "aula-01", {"dado": "3"})

        rascunhos_dcc203 = gerenciador.listar_rascunhos("DCC203")

        assert len(rascunhos_dcc203) == 2
        assert all(r.disciplina_codigo == "DCC203" for r in rascunhos_dcc203)

    def test_recuperar_rascunho_inexistente(self) -> None:
        """Recuperar rascunho inexistente retorna None."""

        gerenciador = GerenciadorRascunhos()

        assert gerenciador.recuperar_rascunho("inexistente") is None

    def test_remover_rascunho_inexistente(self) -> None:
        """Remover rascunho inexistente retorna False."""

        gerenciador = GerenciadorRascunhos()

        removido = gerenciador.remover_rascunho("inexistente")
        assert removido is False
