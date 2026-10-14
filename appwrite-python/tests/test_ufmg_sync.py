from datetime import UTC, datetime

import pytest

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession
from ufmg_sync import UFMGSyncService, _date


def _enrollment() -> dict[str, object]:
    return {
        "code": "ELE028",
        "name": "Circuitos",
        "workload": 30,
        "term": "2026-2",
        "starts_on": "2026-08-03T00:00:00Z",
        "ends_on": "2026-12-05T00:00:00Z",
        "meetings": [{"weekday": 1, "start_minutes": 450, "lesson_count": 2}],
    }


class _Sessions:
    def __init__(self, session: UFMGSession | None) -> None:
        self.session = session
        self.deleted = False

    def load(self, user_id: str, *, now: int) -> UFMGSession | None:
        assert user_id == "user"
        assert now == 10
        return self.session

    def delete(self, user_id: str) -> None:
        assert user_id == "user"
        self.deleted = True
        self.session = None


class _Enrollments:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values
        self.calls = 0
        self.failure: Exception | None = None

    def fetch(self, token: str) -> list[dict[str, object]]:
        assert token == "private-token"
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.values


class _CourseImporter:
    def __init__(self) -> None:
        self.received: list[dict[str, object]] | None = None

    def import_enrollments(self, values: list[dict[str, object]]) -> dict[str, int]:
        self.received = values
        return {"created": 1, "existing": 0, "total": 1}


class _ScheduleImporter:
    def __init__(self, courses: _CourseImporter) -> None:
        self._courses = courses
        self.received: list[dict[str, object]] | None = None

    def import_enrollments(self, values: list[dict[str, object]]) -> dict[str, int]:
        assert self._courses.received is values
        self.received = values
        return {
            "total": 1,
            "updated": 1,
            "unchanged": 0,
            "conflicts": 0,
            "missing_courses": 0,
            "meetings_imported": 1,
        }


class _DateImporter:
    def __init__(self, schedules: _ScheduleImporter) -> None:
        self._schedules = schedules
        self.called = False

    def import_dates(self, user_id: str, *, now: int) -> dict[str, int]:
        assert self._schedules.received is not None
        assert (user_id, now) == ("user", 10)
        self.called = True
        return {
            "total": 2,
            "matched": 1,
            "unmatched": 1,
            "created": 1,
            "updated": 0,
            "unchanged": 0,
        }


def _service(
    now: datetime,
    *,
    sessions: _Sessions | None = None,
    enrollments: _Enrollments | None = None,
) -> tuple[
    UFMGSyncService, _Sessions, _Enrollments, _CourseImporter, _ScheduleImporter, _DateImporter
]:
    session_store = sessions or _Sessions(UFMGSession("private-token", 1, 99))
    client = enrollments or _Enrollments([_enrollment()])
    courses = _CourseImporter()
    schedules = _ScheduleImporter(courses)
    dates = _DateImporter(schedules)
    return (
        UFMGSyncService(
            session_store,
            client,
            courses,
            schedules,
            dates,
            clock=lambda: now,
        ),
        session_store,
        client,
        courses,
        schedules,
        dates,
    )


def test_sync_fetches_once_and_reuses_the_snapshot_for_every_stage() -> None:
    service, _, client, courses, schedules, dates = _service(datetime(2026, 8, 10, 12, tzinfo=UTC))

    result = service.sync("user", now=10)

    assert client.calls == 1
    assert courses.received is schedules.received
    assert dates.called
    assert result == {
        "courses": {"created": 1, "existing": 0, "total": 1},
        "schedules": {
            "total": 1,
            "updated": 1,
            "unchanged": 0,
            "conflicts": 0,
            "missing_courses": 0,
            "meetings_imported": 1,
        },
        "dates": {
            "total": 2,
            "matched": 1,
            "unmatched": 1,
            "created": 1,
            "updated": 0,
            "unchanged": 0,
        },
        "checked_at": "2026-08-10T12:00:00Z",
        "next_automatic_sync_at": "2026-08-11T12:00:00Z",
    }


def test_siga_sync_fetches_once_without_contacting_moodle() -> None:
    service, _, client, courses, schedules, dates = _service(datetime(2026, 8, 10, 12, tzinfo=UTC))

    result = service.sync_siga("user", now=10)

    assert client.calls == 1
    assert courses.received is schedules.received
    assert not dates.called
    assert result == {
        "courses": {"created": 1, "existing": 0, "total": 1},
        "schedules": {
            "total": 1,
            "updated": 1,
            "unchanged": 0,
            "conflicts": 0,
            "missing_courses": 0,
            "meetings_imported": 1,
        },
        "checked_at": "2026-08-10T12:00:00Z",
        "next_automatic_sync_at": "2026-08-11T12:00:00Z",
    }


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (
            datetime(2026, 10, 13, 12, tzinfo=UTC),
            "2026-12-06T00:00:00Z",
        ),
        (
            datetime(2026, 12, 20, 12, tzinfo=UTC),
            "2026-12-27T12:00:00Z",
        ),
    ],
)
def test_sync_backs_off_after_enrollment_window_and_between_terms(
    now: datetime, expected: str
) -> None:
    service, *_ = _service(now)

    result = service.sync("user", now=10)

    assert result["next_automatic_sync_at"] == expected


def test_sync_requires_a_live_session_and_deletes_a_rejected_one() -> None:
    missing, *_ = _service(datetime(2026, 8, 10, tzinfo=UTC), sessions=_Sessions(None))
    with pytest.raises(UFMGReauthenticationRequired):
        missing.sync("user", now=10)

    sessions = _Sessions(UFMGSession("private-token", 1, 99))
    enrollments = _Enrollments([_enrollment()])
    enrollments.failure = UFMGReauthenticationRequired()
    expired, sessions, *_ = _service(
        datetime(2026, 8, 10, tzinfo=UTC),
        sessions=sessions,
        enrollments=enrollments,
    )

    with pytest.raises(UFMGReauthenticationRequired):
        expired.sync("user", now=10)

    assert sessions.deleted


def test_sync_uses_a_bounded_retry_when_no_enrollment_is_available() -> None:
    service, *_ = _service(
        datetime(2026, 8, 10, 12, tzinfo=UTC),
        enrollments=_Enrollments([]),
    )

    result = service.sync("user", now=10)

    assert result["next_automatic_sync_at"] == "2026-08-17T12:00:00Z"


@pytest.mark.parametrize("value", [None, 1, "2026-08-03T00:00:00"])
def test_sync_rejects_untrusted_or_timezone_free_dates(value: object) -> None:
    with pytest.raises(ValueError, match="invalid enrollment date"):
        _date(value)
