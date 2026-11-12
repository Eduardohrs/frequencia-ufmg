"""Structured, privacy-safe application logging."""

import json
import logging
import sys
from datetime import UTC, datetime

EXTRA_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


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
