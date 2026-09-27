"""Tests for the object-oriented academic domain structure."""

import pytest

from frequencia_ufmg.models import (
    ConfiguracaoSessao,
    Disciplina,
    EstadoPing,
    NumeroChamadas,
    QuantidadeAulas,
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
