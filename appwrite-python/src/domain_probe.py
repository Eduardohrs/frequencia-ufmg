"""Representative attendance rule used by the Appwrite feasibility gate."""

from enum import StrEnum


class AttendanceStatus(StrEnum):
    """Attendance outcomes with an automatic absence value."""

    PRESENT = "presente"
    LATE = "chegou_atrasado"
    LEFT_EARLY = "saiu_mais_cedo"
    ABSENT = "ausente"


def calculate_absences(status: AttendanceStatus, lessons: int, calls: int) -> int:
    """Apply the same one/two-call rule used by the product."""

    if lessons not in (1, 2, 4) or calls not in (1, 2) or (lessons == 1 and calls == 2):
        raise ValueError("invalid session configuration")
    if status is AttendanceStatus.ABSENT:
        return lessons
    if calls == 2 and status in (AttendanceStatus.LATE, AttendanceStatus.LEFT_EARLY):
        return lessons // 2
    return 0
