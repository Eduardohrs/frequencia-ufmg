"""Contract tests shared with the Dart attendance domain."""

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest

from frequencia_ufmg.models import (
    ConfiguracaoSessao,
    EstadoPing,
    NumeroChamadas,
    QuantidadeAulas,
    SessaoAula,
    SituacaoFrequencia,
)

SHARED_CASES_PATH = (
    Path(__file__).resolve().parents[2] / "shared" / "attendance_cases.json"
)


class AttendanceCase(TypedDict):
    """One language-neutral attendance decision."""

    id: str
    aulas: int
    chamadas: int
    primeiro_ping: str
    segundo_ping: str
    situacao: str
    faltas: int | None


class SharedCases(TypedDict):
    """Versioned shape consumed by both implementations."""

    versao: int
    casos: list[AttendanceCase]


@pytest.fixture(scope="module")
def shared_cases() -> SharedCases:
    """Load the repository's single source of cross-language examples."""

    return cast(
        SharedCases,
        json.loads(SHARED_CASES_PATH.read_text(encoding="utf-8")),
    )


def test_shared_cases_cover_every_ping_pair_for_every_valid_configuration(
    shared_cases: SharedCases,
) -> None:
    """No supported session configuration can drift between Python and Dart."""

    assert shared_cases["versao"] == 1
    assert len(shared_cases["casos"]) == 45
    assert len({case["id"] for case in shared_cases["casos"]}) == 45

    expected_pairs = {
        (first.value, second.value) for first in EstadoPing for second in EstadoPing
    }
    expected_configurations = {
        (QuantidadeAulas.UMA.value, NumeroChamadas.UMA.value),
        (QuantidadeAulas.DUAS.value, NumeroChamadas.UMA.value),
        (QuantidadeAulas.DUAS.value, NumeroChamadas.DUAS.value),
        (QuantidadeAulas.QUATRO.value, NumeroChamadas.UMA.value),
        (QuantidadeAulas.QUATRO.value, NumeroChamadas.DUAS.value),
    }

    actual_configurations = {
        (case["aulas"], case["chamadas"]) for case in shared_cases["casos"]
    }
    assert actual_configurations == expected_configurations
    for configuration in expected_configurations:
        actual_pairs = {
            (case["primeiro_ping"], case["segundo_ping"])
            for case in shared_cases["casos"]
            if (case["aulas"], case["chamadas"]) == configuration
        }
        assert actual_pairs == expected_pairs


def test_python_domain_matches_every_shared_attendance_case(
    shared_cases: SharedCases,
) -> None:
    """Python remains the executable reference for the shared contract."""

    for case in shared_cases["casos"]:
        session = SessaoAula(
            case["id"],
            ConfiguracaoSessao(
                QuantidadeAulas(case["aulas"]),
                NumeroChamadas(case["chamadas"]),
            ),
        )

        situation = session.classificar(
            EstadoPing(case["primeiro_ping"]),
            EstadoPing(case["segundo_ping"]),
        )

        assert situation is SituacaoFrequencia(case["situacao"]), case["id"]
        assert session.calcular_faltas(situation) == case["faltas"], case["id"]
