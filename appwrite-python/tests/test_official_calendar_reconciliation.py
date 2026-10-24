import pytest

from official_calendar_reconciliation import (
    InvalidOfficialCalendarReconciliation,
    preview_official_calendar,
)

SOURCE = "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2026"


def _event(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "title": "Feriado: Nossa Senhora Aparecida.",
        "campus": "all",
        "start_date": "2026-10-12",
        "end_date": "2026-10-12",
        "effect": "holiday",
        "confidence": "official",
    }
    value.update(changes)
    return value


def _session(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "session-1",
        "starts_at": "2026-10-12T22:00:00Z",
        "ends_at": "2026-10-12T23:40:00Z",
        "lesson_count": 2,
        "call_count": 1,
        "first_ping": None,
        "second_ping": None,
        "attendance_status": None,
        "absences": None,
        "calendar_status": "scheduled",
        "assessment_title": None,
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }
    value.update(changes)
    return value


def test_previews_exact_holiday_changes_and_preserves_existing_states() -> None:
    result = preview_official_calendar(
        [
            _event(),
            _event(
                title="Semana do Conhecimento",
                campus="belo_horizonte",
                effect="no_assessments",
                start_date="2026-10-20",
                end_date="2026-10-23",
            ),
        ],
        [
            _session(),
            _session(id="already", calendar_status="holiday"),
            _session(id="manual", calendar_status="no_call"),
            _session(
                id="other-day", starts_at="2026-10-13T03:00:00Z", ends_at="2026-10-13T04:40:00Z"
            ),
        ],
        source_url=SOURCE,
    )

    assert result["counts"] == {
        "candidates": 1,
        "unchanged": 1,
        "protected": 1,
        "advisories": 1,
    }
    assert result["candidates"] == [
        {
            "session_id": "session-1",
            "date": "2026-10-12",
            "starts_at": "2026-10-12T22:00:00Z",
            "ends_at": "2026-10-12T23:40:00Z",
            "events": [
                {
                    "title": "Feriado: Nossa Senhora Aparecida.",
                    "source_url": SOURCE,
                    "confidence": "official",
                }
            ],
            "from": "scheduled",
            "to": "holiday",
        }
    ]
    assert result["unchanged"][0]["session_id"] == "already"
    assert result["protected"][0]["session_id"] == "manual"
    assert result["protected"][0]["status"] == "no_call"
    assert result["protected"][0]["reason"] == "existing_calendar_status_preserved"
    assert result["advisories"][0]["effect"] == "no_assessments"


def test_uses_sao_paulo_date_and_supports_multi_day_holidays() -> None:
    result = preview_official_calendar(
        [_event(start_date="2026-10-11", end_date="2026-10-12")],
        [
            _session(
                starts_at="2026-10-13T01:30:00Z", ends_at="2026-10-13T02:30:00Z", lesson_count=1
            )
        ],
        source_url=SOURCE,
    )

    assert result["candidates"][0]["date"] == "2026-10-12"


def test_keeps_campus_specific_holidays_as_advisories_until_course_campus_exists() -> None:
    result = preview_official_calendar(
        [_event(campus="belo_horizonte")],
        [_session()],
        source_url=SOURCE,
    )

    assert result["candidates"] == []
    assert result["advisories"][0]["campus"] == "belo_horizonte"


@pytest.mark.parametrize(
    "events,sessions",
    [
        ({}, []),
        ([_event()] * 501, []),
        ([_event()], [_session()] * 501),
        ([_event(unexpected=True)], []),
        ([_event(title="")], []),
        ([_event(title="x" * 501)], []),
        ([_event(campus="other")], []),
        ([_event(effect="other")], []),
        ([_event(confidence="guess")], []),
        ([_event(start_date="bad")], []),
        ([_event(start_date="2026-10-13", end_date="2026-10-12")], []),
        ([_event(start_date="2026-01-01", end_date="2026-02-02")], []),
        ([_event(start_date="2026-11-01", end_date="2026-11-01")], []),
        ([_event()], [_session(unexpected=True)]),
        ([_event()], [_session(starts_at="2026-10-12T22:00:00")]),
    ],
)
def test_rejects_untrusted_or_unbounded_inputs(events: object, sessions: object) -> None:
    with pytest.raises(InvalidOfficialCalendarReconciliation):
        preview_official_calendar(events, sessions, source_url=SOURCE)  # type: ignore[arg-type]


def test_rejects_untrusted_source_url() -> None:
    for source in (
        None,
        "https://example.com",
        "https://www.ufmg.br/a-universidade/calendario-escolar/evil?mes=10&ano=2026",
        "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=13&ano=2026",
        "https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2025",
    ):
        with pytest.raises(InvalidOfficialCalendarReconciliation):
            preview_official_calendar([_event()], [], source_url=source)  # type: ignore[arg-type]


def test_reports_multiple_official_events_for_the_same_session() -> None:
    result = preview_official_calendar(
        [_event(), _event(title="Feriado: Evento local institucional")],
        [_session()],
        source_url=SOURCE,
    )

    assert [event["title"] for event in result["candidates"][0]["events"]] == [
        "Feriado: Nossa Senhora Aparecida.",
        "Feriado: Evento local institucional",
    ]
