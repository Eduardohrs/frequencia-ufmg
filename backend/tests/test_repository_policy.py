"""Tests for repository-level security and supply-chain contracts."""

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_firebase_hosting_declares_baseline_security_headers() -> None:
    """The deployed web client keeps its browser hardening contract."""

    firebase_config = json.loads(
        (REPOSITORY_ROOT / "firebase.json").read_text(encoding="utf-8")
    )
    headers = {
        header["key"]: header["value"]
        for rule in firebase_config["hosting"]["headers"]
        for header in rule["headers"]
    }

    assert headers["Strict-Transport-Security"].startswith("max-age=")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"


def test_mutable_web_boot_files_are_never_served_stale() -> None:
    """A deploy must not leave browsers running the previous Flutter bundle."""

    firebase_config = json.loads(
        (REPOSITORY_ROOT / "firebase.json").read_text(encoding="utf-8")
    )
    cache_control_by_source = {
        rule["source"]: header["value"]
        for rule in firebase_config["hosting"]["headers"]
        for header in rule["headers"]
        if header["key"].lower() == "cache-control"
    }
    mutable_sources = {
        "/",
        "/index.html",
        "/flutter_bootstrap.js",
        "/flutter_service_worker.js",
        "/main.dart.js",
    }

    assert mutable_sources <= cache_control_by_source.keys()
    assert all(
        "no-cache" in cache_control_by_source[source]
        and "no-store" in cache_control_by_source[source]
        for source in mutable_sources
    )


def test_github_actions_are_pinned_to_immutable_commits() -> None:
    """Third-party workflow code cannot change behind a mutable version tag."""

    workflows = REPOSITORY_ROOT / ".github" / "workflows"
    uses_pattern = re.compile(r"^\s*-\s+uses:\s+[^@\s]+@([^#\s]+)")
    references = [
        match.group(1)
        for workflow in workflows.glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if (match := uses_pattern.match(line))
    ]

    assert references
    assert all(re.fullmatch(r"[0-9a-f]{40}", reference) for reference in references)


# ==================== Sessão 55,35 - Testes de Regressão ====================


class TestSession55_35:
    """Testes de regressão para sessão 55,35."""

    def test_protecao_gravacao_telemetria_repetida(self) -> None:
        """Proteção de gravação contra telemetria repetida funciona."""
        from frequencia_ufmg.logging_config import TelemetryKey, TelemetryRecorder

        recorder = TelemetryRecorder()
        
        # Primeiro relato deve ser gravado
        key1 = TelemetryKey("attendance", "record", "session", "aula-01")
        first_result = recorder.record(
            key1.category, key1.action, key1.entity_type, key1.entity_id
        )
        
        # Segundo relato idêntico deve ser bloqueado
        second_result = recorder.record(
            key1.category, key1.action, key1.entity_type, key1.entity_id
        )
        
        assert first_result is True
        assert second_result is False

    def test_preservacao_erro_429(self) -> None:
        """Preservação do erro 429 no diagnóstico."""
        from frequencia_ufmg.logging_config import TelemetryRecorder

        recorder = TelemetryRecorder()
        
        info = recorder.record_429(
            request_id="test-429",
            retry_after=60.0,
            context={"path": "/api/test"}
        )
        
        assert info["error_code"] == "RATE_LIMITED"
        assert info["request_id"] == "test-429"
        assert info["retry_after"] == 60.0
        
        # Verificar que pode ser recuperado
        recovered = recorder.get_rate_limit("test-429")
        assert recovered is not None
        assert recovered["error_code"] == "RATE_LIMITED"

    def test_preservacao_resource_exhausted(self) -> None:
        """Preservação do RESOURCE_EXHAUSTED no diagnóstico."""
        from frequencia_ufmg.logging_config import TelemetryRecorder

        recorder = TelemetryRecorder()
        
        info = recorder.record_resource_exhausted(
            request_id="test-re",
            context={"operation": "write"}
        )
        
        assert info["error_code"] == "RESOURCE_EXHAUSTED"
        assert info["request_id"] == "test-re"
        
        # Verificar que pode ser recuperado
        recovered = recorder.get_rate_limit("test-re")
        assert recovered is not None
        assert recovered["error_code"] == "RESOURCE_EXHAUSTED"

    def test_frequencia_preservada(self) -> None:
        """Registros de frequência são preservados."""
        from frequencia_ufmg.models import (
            ConfiguracaoSessao,
            Disciplina,
            NumeroChamadas,
            QuantidadeAulas,
            SessaoAula,
            SituacaoFrequencia,
        )

        disciplina = Disciplina("DCC203", "POO", 60)
        sessao = SessaoAula(
            "aula-01",
            ConfiguracaoSessao(QuantidadeAulas.DUAS, NumeroChamadas.UMA)
        )
        disciplina.adicionar_sessao(sessao)
        
        # Registrar frequência
        registro = disciplina.registrar_frequencia("aula-01", SituacaoFrequencia.PRESENTE)
        
        # Verificar que frequência é preservada
        assert registro.faltas == 0
        assert registro.situacao == SituacaoFrequencia.PRESENTE
        
        # Verificar resumo
        resumo = disciplina.resumo()
        assert resumo.faltas_consumidas == 0

