"""Structured, privacy-safe application logging."""

import hashlib
import json
import logging
import sys
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


@dataclass(frozen=True, slots=True)
class TelemetryKey:
    """Chave imutável para identificação única de relatórios de telemetria."""

    category: str
    action: str
    entity_type: str
    entity_id: str

    def to_hash(self) -> str:
        """Gera um hash estável para deduplicação."""
        content = f"{self.category}:{self.action}:{self.entity_type}:{self.entity_id}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TelemetryDeduplicator:
    """Protege contra gravação repetida de telemetria usando janela de tempo."""

    def __init__(self, window_seconds: float = 300.0) -> None:
        """Inicializa com janela de deduplicação (padrão: 5 minutos)."""
        self._window = timedelta(seconds=window_seconds)
        self._lock = threading.RLock()
        self._last_reports: dict[str, datetime] = {}

    def should_report(self, key: TelemetryKey) -> bool:
        """Verifica se um relatório pode ser gravado (não duplicado na janela)."""
        hash_key = key.to_hash()
        now = datetime.now(UTC)
        with self._lock:
            last_time = self._last_reports.get(hash_key)
            if last_time is None:
                self._last_reports[hash_key] = now
                return True
            if now - last_time >= self._window:
                self._last_reports[hash_key] = now
                return True
            return False

    def clear_old_entries(self) -> int:
        """Remove entradas antigas do cache de deduplicação."""
        now = datetime.now(UTC)
        threshold = now - self._window
        with self._lock:
            old_keys = [k for k, v in self._last_reports.items() if v < threshold]
            for key in old_keys:
                del self._last_reports[key]
            return len(old_keys)


class TelemetryRecorder:
    """Gravador de telemetria com proteção contra duplicação e limite de taxa."""

    def __init__(self, deduplicator: TelemetryDeduplicator | None = None) -> None:
        """Inicializa com deduplicador opcional."""
        self._deduplicator = deduplicator or TelemetryDeduplicator()
        self._lock = threading.RLock()

    def record(
        self,
        category: str,
        action: str,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Grava telemetria se não for duplicata. Retorna True se gravado."""
        key = TelemetryKey(category, action, entity_type, entity_id)
        if not self._deduplicator.should_report(key):
            return False
        return True

    def record_429(
        self,
        request_id: str,
        retry_after: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra ocorrência de HTTP 429 para diagnóstico."""
        info = {
            "error_code": "RATE_LIMITED",
            "request_id": request_id,
            "retry_after": retry_after,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if context:
            info["context"] = context
        with self._lock:
            # Armazenar para diagnóstico posterior
            if not hasattr(self, "_rate_limits"):
                self._rate_limits: dict[str, dict[str, Any]] = {}
            self._rate_limits[request_id] = info
        return info

    def record_resource_exhausted(
        self,
        request_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Registra ocorrência de RESOURCE_EXHAUSTED para diagnóstico."""
        info = {
            "error_code": "RESOURCE_EXHAUSTED",
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if context:
            info["context"] = context
        with self._lock:
            if not hasattr(self, "_rate_limits"):
                self._rate_limits: dict[str, dict[str, Any]] = {}
            self._rate_limits[request_id] = info
        return info

    def get_rate_limit(self, request_id: str) -> dict[str, Any] | None:
        """Recupera informações de limite de taxa."""
        with self._lock:
            return getattr(self, "_rate_limits", {}).get(request_id)


# Instância global para uso no backend
telemetry_recorder = TelemetryRecorder()


class JsonFormatter(logging.Formatter):
    """Serialize records for local tools and future managed runtimes."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a record without request bodies, query strings, or headers."""

        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **{field: getattr(record, field, None) for field in EXTRA_FIELDS},
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Send one-line JSON records to stdout."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)
