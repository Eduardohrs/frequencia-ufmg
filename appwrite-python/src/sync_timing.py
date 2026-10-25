"""Structured duration telemetry for academic synchronization stages."""

from collections.abc import Callable, Mapping
from time import monotonic

Telemetry = Callable[[str, Mapping[str, object]], None]


def timed_stage[T](
    stage: str,
    action: Callable[[], T],
    *,
    telemetry: Telemetry | None = None,
    clock: Callable[[], float] = monotonic,
    fields: Mapping[str, object] | None = None,
) -> T:
    """Run one stage and report its duration without making logging a dependency."""

    started = clock()
    context = dict(fields or {})
    try:
        result = action()
    except Exception as error:
        _emit(
            telemetry,
            "academic_sync_stage_failed",
            {
                "stage": stage,
                "duration_ms": round((clock() - started) * 1000),
                "exception_type": type(error).__name__,
                "reason": str(error) or type(error).__name__,
                **context,
            },
        )
        raise
    _emit(
        telemetry,
        "academic_sync_stage_completed",
        {
            "stage": stage,
            "duration_ms": round((clock() - started) * 1000),
            **context,
        },
    )
    return result


def _emit(telemetry: Telemetry | None, event: str, fields: Mapping[str, object]) -> None:
    if telemetry is None:
        return
    try:
        telemetry(event, fields)
    except Exception:
        # Diagnostics must never become a product dependency.
        return
