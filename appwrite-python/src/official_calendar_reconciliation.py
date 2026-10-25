"""Preview safe session changes derived from the official UFMG calendar."""

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from schedule_service import InvalidSchedule, validate_saved_session

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_EVENTS = 500
MAX_SESSIONS = 500
SOURCE_URL = re.compile(
    r"https://www\.ufmg\.br/a-universidade/calendario-escolar/\?mes=(\d{2})&ano=(\d{4})"
)


class InvalidOfficialCalendarReconciliation(ValueError):
    pass


def preview_official_calendar(
    events: object,
    sessions: Iterable[Mapping[str, Any]],
    *,
    source_url: str,
) -> dict[str, object]:
    """Return explicit holiday candidates without mutating persisted sessions."""

    source_match = SOURCE_URL.fullmatch(source_url) if isinstance(source_url, str) else None
    if source_match is None or not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise InvalidOfficialCalendarReconciliation("invalid official calendar events")
    source_month, source_year = (int(part) for part in source_match.groups())
    if not 1 <= source_month <= 12 or not 2026 <= source_year <= 2099:
        raise InvalidOfficialCalendarReconciliation("invalid official calendar events")
    saved = list(sessions)
    if len(saved) > MAX_SESSIONS:
        raise InvalidOfficialCalendarReconciliation("too many sessions")
    try:
        valid_sessions = [validate_saved_session(item) for item in saved]
        valid_events = [
            _event(item, source_year=source_year, source_month=source_month) for item in events
        ]
    except (InvalidSchedule, TypeError, ValueError):
        raise InvalidOfficialCalendarReconciliation("invalid reconciliation input") from None

    holiday_events = [
        event for event in valid_events if event["effect"] == "holiday" and event["campus"] == "all"
    ]
    candidates: list[dict[str, object]] = []
    unchanged: list[dict[str, object]] = []
    protected: list[dict[str, object]] = []
    for session in valid_sessions:
        day = _local_date(str(session["starts_at"]))
        matches = [event for event in holiday_events if event["start"] <= day <= event["end"]]
        if not matches:
            continue
        summary = _session_summary(session, day, matches, source_url)
        status = session["calendar_status"]
        if status == "scheduled":
            candidates.append({**summary, "from": "scheduled", "to": "holiday"})
        elif status == "holiday":
            unchanged.append({**summary, "status": "holiday"})
        else:
            protected.append(
                {
                    **summary,
                    "status": status,
                    "reason": "existing_calendar_status_preserved",
                }
            )

    advisories = [
        {
            "title": event["title"],
            "campus": event["campus"],
            "start_date": event["start"].isoformat(),
            "end_date": event["end"].isoformat(),
            "effect": event["effect"],
            "source_url": source_url,
        }
        for event in valid_events
        if event not in holiday_events
    ]
    return {
        "candidates": candidates,
        "unchanged": unchanged,
        "protected": protected,
        "advisories": advisories,
        "counts": {
            "candidates": len(candidates),
            "unchanged": len(unchanged),
            "protected": len(protected),
            "advisories": len(advisories),
        },
    }


def _event(value: object, *, source_year: int, source_month: int) -> dict[str, Any]:
    fields = {
        "title",
        "campus",
        "start_date",
        "end_date",
        "effect",
        "confidence",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError
    title = value["title"]
    campus = value["campus"]
    effect = value["effect"]
    confidence = value["confidence"]
    if (
        not isinstance(title, str)
        or not title
        or len(title) > 500
        or campus not in {"all", "belo_horizonte", "montes_claros"}
        or effect not in {"holiday", "class_replacement", "no_assessments", "informational"}
        or confidence != "official"
    ):
        raise ValueError
    start = date.fromisoformat(str(value["start_date"]))
    end = date.fromisoformat(str(value["end_date"]))
    if (
        start.year != source_year
        or start.month != source_month
        or end < start
        or (end - start).days > 31
    ):
        raise ValueError
    return {
        "title": title,
        "campus": campus,
        "start": start,
        "end": end,
        "effect": effect,
    }


def _local_date(value: str) -> date:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.astimezone(SAO_PAULO).date()


def _session_summary(
    session: Mapping[str, Any],
    day: date,
    events: list[dict[str, Any]],
    source_url: str,
) -> dict[str, object]:
    return {
        "session_id": session["id"],
        "date": day.isoformat(),
        "starts_at": session["starts_at"],
        "ends_at": session["ends_at"],
        "events": [
            {
                "title": event["title"],
                "source_url": source_url,
                "confidence": "official",
            }
            for event in events
        ],
    }
