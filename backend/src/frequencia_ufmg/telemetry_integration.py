"""Integração de telemetria com deduplicação para uso em produção."""

import threading
from typing import Any

from frequencia_ufmg.logging_config import (
    TelemetryDeduplicator,
    TelemetryKey,
    TelemetryRecorder,
)


class ProductionTelemetryRecorder(TelemetryRecorder):
    """Gravador de telemetria integrado aos emissores de produção."""

    _instance: "ProductionTelemetryRecorder | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "ProductionTelemetryRecorder":
        """Singleton para garantir uma única instância global."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, window_seconds: float = 300.0) -> None:
        """Inicializa com deduplicador e janela configurável."""
        with self._lock:
            if not hasattr(self, "_initialized"):
                super().__init__(TelemetryDeduplicator(window_seconds))
                self._initialized = True
                self._report_count: dict[str, int] = {}
                self._report_lock = threading.RLock()

    def record_production_report(
        self,
        category: str,
        action: str,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Registra relatório de produção com deduplicação."""
        key = TelemetryKey(category, action, entity_type, entity_id)
        if not self._deduplicator.should_report(key):
            return False

        with self._report_lock:
            hash_key = key.to_hash()
            self._report_count[hash_key] = self._report_count.get(hash_key, 0) + 1

        return True

    def get_report_count(self, category: str, action: str, entity_type: str, entity_id: str) -> int:
        """Retorna quantas vezes um relatório foi tentado (inclusive bloqueados)."""
        key = TelemetryKey(category, action, entity_type, entity_id)
        hash_key = key.to_hash()
        with self._report_lock:
            return self._report_count.get(hash_key, 0)


# Instância global para produção
production_telemetry = ProductionTelemetryRecorder()
