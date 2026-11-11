"""Frequência UFMG backend package."""

from frequencia_ufmg.logging_config import (
    TelemetryDeduplicator,
    TelemetryKey,
    TelemetryRecorder,
    telemetry_recorder,
)
from frequencia_ufmg.telemetry_integration import (
    ProductionTelemetryRecorder,
    production_telemetry,
)
from frequencia_ufmg.persistence_integration import (
    DraftStorage,
    PendencyStorage,
    PersistentCentralPendencias,
    PersistentGerenciadorRascunhos,
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
    "DraftStorage",
    "EstadoPing",
    "GerenciadorRascunhos",
    "NumeroChamadas",
    "PendencyStorage",
    "PendenciaHorario",
    "PersistentCentralPendencias",
    "PersistentGerenciadorRascunhos",
    "PoliticaChamadaUnica",
    "PoliticaDuasChamadas",
    "PoliticaFrequencia",
    "ProductionTelemetryRecorder",
    "QuantidadeAulas",
    "RascunhoCadastro",
    "RegistroFrequencia",
    "ResumoDisciplina",
    "SessaoAula",
    "SituacaoFrequencia",
    "TelemetryDeduplicator",
    "TelemetryKey",
    "TelemetryRecorder",
    "production_telemetry",
    "telemetry_recorder",
]

