"""Frequência UFMG backend package."""

from frequencia_ufmg.logging_config import (
    TelemetryDeduplicator,
    TelemetryKey,
    TelemetryRecorder,
    telemetry_recorder,
)
from frequencia_ufmg.models import (
    CentralPendencias,
    ConfiguracaoSessao,
    DecisaoHorario,
    Disciplina,
    EstadoPing,
    GerenciadorRascunhos,
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
    "CentralPendencias",
    "ConfiguracaoSessao",
    "DecisaoHorario",
    "Disciplina",
    "EstadoPing",
    "GerenciadorRascunhos",
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
    "TelemetryDeduplicator",
    "TelemetryKey",
    "TelemetryRecorder",
    "telemetry_recorder",
]

