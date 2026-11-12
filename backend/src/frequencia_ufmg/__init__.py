"""Frequência UFMG backend package."""

# O deploy do Appwrite empacota apenas este __init__ e models.py do pacote
# compartilhado; portanto nenhuma importação aqui pode depender de módulos
# somente de backend (como logging_config). A telemetria de produção vive em
# appwrite-python/src/telemetry_guard.py.
from frequencia_ufmg.models import (
    ConfiguracaoSessao,
    DecisaoHorario,
    Disciplina,
    EstadoPing,
    NumeroChamadas,
    PendenciaHorario,
    PoliticaChamadaUnica,
    PoliticaDuasChamadas,
    PoliticaFrequencia,
    QuantidadeAulas,
    RascunhoCadastro,
    RegistroFrequencia,
    ResumoDisciplina,
    SessaoAula,
    SituacaoFrequencia,
)

__all__ = [
    "ConfiguracaoSessao",
    "DecisaoHorario",
    "Disciplina",
    "EstadoPing",
    "NumeroChamadas",
    "PendenciaHorario",
    "PoliticaChamadaUnica",
    "PoliticaDuasChamadas",
    "PoliticaFrequencia",
    "QuantidadeAulas",
    "RascunhoCadastro",
    "RegistroFrequencia",
    "ResumoDisciplina",
    "SessaoAula",
    "SituacaoFrequencia",
]

