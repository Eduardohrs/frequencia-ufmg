import pytest

from domain_probe import AttendanceStatus, calculate_absences


@pytest.mark.parametrize(
    ("status", "lessons", "calls", "expected"),
    [
        (AttendanceStatus.PRESENT, 4, 1, 0),
        (AttendanceStatus.LATE, 4, 1, 0),
        (AttendanceStatus.LEFT_EARLY, 4, 1, 0),
        (AttendanceStatus.ABSENT, 4, 1, 4),
        (AttendanceStatus.PRESENT, 4, 2, 0),
        (AttendanceStatus.LATE, 4, 2, 2),
        (AttendanceStatus.LEFT_EARLY, 4, 2, 2),
        (AttendanceStatus.ABSENT, 4, 2, 4),
    ],
)
def test_calculate_absences_matches_the_product_rules(
    status: AttendanceStatus,
    lessons: int,
    calls: int,
    expected: int,
) -> None:
    assert calculate_absences(status, lessons, calls) == expected


@pytest.mark.parametrize(("lessons", "calls"), [(3, 1), (1, 2), (2, 3)])
def test_calculate_absences_rejects_invalid_session_configuration(
    lessons: int,
    calls: int,
) -> None:
    with pytest.raises(ValueError):
        calculate_absences(AttendanceStatus.PRESENT, lessons, calls)
