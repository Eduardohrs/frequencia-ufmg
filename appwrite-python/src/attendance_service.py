"""HTTP-facing adapter for the canonical Python attendance domain."""

from frequencia_ufmg.models import (
    ConfiguracaoSessao,
    EstadoPing,
    NumeroChamadas,
    QuantidadeAulas,
    SessaoAula,
    SituacaoFrequencia,
)

PING_FIELDS = {"calls", "first_ping", "lessons", "second_ping"}
STATUS_FIELDS = {"calls", "lessons", "status"}


class InvalidAttendanceRequest(ValueError):
    """Public payload does not satisfy the bounded attendance contract."""


def evaluate_attendance(payload: object) -> dict[str, str | int | None]:
    """Evaluate one session using the single POO model shown in the course."""

    if not isinstance(payload, dict):
        raise InvalidAttendanceRequest("invalid attendance request")
    fields = set(payload)
    if fields != PING_FIELDS and fields != STATUS_FIELDS:
        raise InvalidAttendanceRequest("invalid attendance request")

    lessons = payload["lessons"]
    calls = payload["calls"]
    if type(lessons) is not int or type(calls) is not int:
        raise InvalidAttendanceRequest("invalid attendance request")

    try:
        session = SessaoAula(
            "api-request",
            ConfiguracaoSessao(
                QuantidadeAulas(lessons),
                NumeroChamadas(calls),
            ),
        )
        if fields == PING_FIELDS:
            first_ping = payload["first_ping"]
            second_ping = payload["second_ping"]
            if not isinstance(first_ping, str) or not isinstance(second_ping, str):
                raise InvalidAttendanceRequest("invalid attendance request")
            status = session.classificar(EstadoPing(first_ping), EstadoPing(second_ping))
        else:
            raw_status = payload["status"]
            if not isinstance(raw_status, str):
                raise InvalidAttendanceRequest("invalid attendance request")
            status = SituacaoFrequencia(raw_status)
    except (TypeError, ValueError) as error:
        raise InvalidAttendanceRequest("invalid attendance request") from error

    return {
        "status": status.value,
        "absences": session.calcular_faltas(status),
    }
