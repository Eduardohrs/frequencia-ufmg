"""Remember the last successful Moodle term-calendar fetch to shrink later windows."""

import json
from typing import Any

from firestore_rest import FirestoreNotFound, FirestoreRestClient
from sync_timing import Telemetry, _emit

_STATE_FIELDS = {"last_fetched_at", "months"}


class MoodleCalendarState:
    """Persist per-term calendar fetch checkpoints as one user document each."""

    def __init__(self, store: FirestoreRestClient, *, telemetry: Telemetry | None = None) -> None:
        self._store = store
        self._telemetry = telemetry

    def load(self, term: str) -> dict[str, Any]:
        try:
            doc = self._store.get_user_document("moodleCalendarState", term)
        except FirestoreNotFound:
            return {}
        try:
            state = json.loads(doc["fields"]["stateJson"]["stringValue"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return {}
        if (
            not isinstance(state, dict)
            or set(state) != _STATE_FIELDS
            or type(state["last_fetched_at"]) is not int
            or not isinstance(state["months"], list)
            or any(
                not isinstance(pair, list)
                or len(pair) != 2
                or any(type(value) is not int for value in pair)
                for pair in state["months"]
            )
        ):
            return {}
        return state

    def save(self, term: str, *, fetched_at: int, months: list[tuple[int, int]]) -> None:
        # Best effort: failing to persist only means the next sync refetches
        # the full term, so this must not fail the sync itself.
        state = {
            "last_fetched_at": fetched_at,
            "months": [[year, month] for year, month in months],
        }
        try:
            self._store.patch_user_document(
                "moodleCalendarState",
                term,
                fields={"stateJson": {"stringValue": json.dumps(state, separators=(",", ":"))}},
            )
        except Exception as error:
            _emit(
                self._telemetry,
                "moodle_calendar_state_persistence_failed",
                {"term": term, "reason": type(error).__name__},
            )
