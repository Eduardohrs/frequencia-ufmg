import json

import pytest

from firestore_rest import FirestoreNotFound
from moodle_calendar_state import MoodleCalendarState


class _Store:
    def __init__(self, doc=None, error: Exception | None = None) -> None:
        self.doc = doc
        self.error = error
        self.patches: list[tuple[tuple[str, ...], dict]] = []

    def get_user_document(self, *segments: str):
        if self.error is not None:
            raise self.error
        if self.doc is None:
            raise FirestoreNotFound("missing")
        raw = self.doc if isinstance(self.doc, str) else json.dumps(self.doc)
        return {"fields": {"stateJson": {"stringValue": raw}}}

    def patch_user_document(self, *segments: str, fields, update_mask=None) -> dict:
        if self.error is not None:
            raise self.error
        self.patches.append((segments, fields))
        return {}


def test_load_returns_empty_when_document_is_missing() -> None:
    assert MoodleCalendarState(_Store()).load("2026-2") == {}


def test_load_returns_empty_when_document_lacks_the_state_field() -> None:
    class BareStore:
        def get_user_document(self, *segments: str):
            return {"fields": {}}

    assert MoodleCalendarState(BareStore()).load("2026-2") == {}


def test_load_returns_persisted_state() -> None:
    state = {"last_fetched_at": 1763424000, "months": [[2026, 10], [2026, 11]]}
    assert MoodleCalendarState(_Store(state)).load("2026-2") == state


@pytest.mark.parametrize(
    "doc",
    [
        "not-json{{{",
        {},
        {"last_fetched_at": "1763424000", "months": []},
        {"last_fetched_at": 1, "months": [[2026]], },
        {"last_fetched_at": 1, "months": [[2026, "10"]]},
        {"last_fetched_at": 1, "months": [], "extra": 1},
        [1, 2],
    ],
)
def test_load_treats_malformed_state_as_missing(doc) -> None:
    store = _Store()
    store.doc = doc
    assert MoodleCalendarState(store).load("2026-2") == {}


def test_save_persists_checkpoint_document() -> None:
    store = _Store()
    MoodleCalendarState(store).save(
        "2026-2", fetched_at=1763424000, months=[(2026, 11), (2026, 12)]
    )
    assert store.patches == [
        (
            ("moodleCalendarState", "2026-2"),
            {
                "stateJson": {
                    "stringValue": json.dumps(
                        {"last_fetched_at": 1763424000, "months": [[2026, 11], [2026, 12]]},
                        separators=(",", ":"),
                    )
                }
            },
        )
    ]


def test_save_failure_is_best_effort_and_reported() -> None:
    events: list[tuple[str, dict]] = []
    store = _Store(error=RuntimeError("firestore down"))
    state = MoodleCalendarState(store, telemetry=lambda e, f: events.append((e, dict(f))))
    state.save("2026-2", fetched_at=1, months=[(2026, 12)])
    assert events == [
        ("moodle_calendar_state_persistence_failed", {"term": "2026-2", "reason": "RuntimeError"})
    ]
