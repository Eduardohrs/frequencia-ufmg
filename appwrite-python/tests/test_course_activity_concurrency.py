"""Bounded concurrency for the Moodle activity snapshot stage."""

import copy
import threading
import time
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

import course_activities as activities_module
import main as function
from activity_snapshot_repository import ActivitySnapshotMissing
from course_activities import (
    DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY,
    MAX_ACTIVITY_SNAPSHOT_CONCURRENCY,
    MIN_ACTIVITY_SNAPSHOT_CONCURRENCY,
    ActivitySnapshotCaptureFailed,
    CourseActivityService,
)
from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    MoodleUnavailable,
)
from moodle_token_store import MoodleTokenStoreUnavailable


def _course(course_id: str) -> dict[str, str]:
    return {"id": course_id, "code": f"ELE{course_id}", "term": "2026-2"}


def _entry(source_id: int, kind: str = "assign") -> dict[str, str]:
    return {
        "source_id": str(source_id),
        "title": f"Activity {source_id}",
        "kind": kind,
        "url": f"https://virtual.ufmg.br/20262/mod/{kind}/view.php?id={source_id}",
        "relevance": "other",
    }


class _Snapshots:
    def __init__(self) -> None:
        self.saved: dict[str, dict[str, object]] = {}

    def load(self, course_id: str) -> dict[str, object]:
        if course_id not in self.saved:
            raise ActivitySnapshotMissing()
        return self.saved[course_id]

    def save(self, course_id: str, snapshot: dict[str, object]) -> None:
        self.saved[course_id] = copy.deepcopy(snapshot)


class _Client:
    def __init__(self, index: dict[str, list[dict[str, str]]], fetch) -> None:
        self._index = index
        self._fetch = fetch
        self.fetch_calls: list[int] = []
        self._lock = threading.Lock()

    def list_activities(self, token, *, term, course_id, course_code):
        return list(self._index[course_code])

    def fetch_activity(self, token, *, term, source_id, kind):
        with self._lock:
            self.fetch_calls.append(source_id)
        return self._fetch(source_id=source_id, kind=kind)


class _IncrementalClient(_Client):
    def __init__(self, index, fetch) -> None:
        super().__init__(index, fetch)
        self.update_calls: list[int] = []
        self.update_course_ids: list[int] = []
        self.bulk_calls: list[int] = []
        self.changed_ids: set[int] = set()
        self.bulk_result: dict[str, dict[str, object]] | None = None
        self.fail_updates = False

    def activity_updates_since(self, token, *, term, course_id, since):
        self.update_calls.append(since)
        self.update_course_ids.append(course_id)
        if self.fail_updates:
            raise InvalidMoodleResponse("updates_unavailable")
        return set(self.changed_ids)

    def fetch_course_activity_bulk(self, *, webservice_token, private_token, term, course_id):
        self.bulk_calls.append(course_id)
        if self.bulk_result is not None:
            return dict(self.bulk_result)
        return {
            entry["source_id"]: {
                "description": f"bulk detail {entry['source_id']}",
                "dates_text": "",
                "has_due_date": False,
                "submission_state": "unknown",
                "submission_text": "",
                "attachments": [],
            }
            for entries in self._index.values()
            for entry in entries
        }


def test_incomplete_course_bulk_uses_module_bulk_before_html_fallback():
    class ModuleBulkClient(_IncrementalClient):
        def __init__(self, index, fetch):
            super().__init__(index, fetch)
            self.module_calls: list[tuple[int, str]] = []

        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_submission_complete": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            self.module_calls.append((kwargs["course_id"], kwargs["kind"]))
            return {
                "1": {
                    "description": "Descrição em lote",
                    "dates_text": "Vencimento: 2026-12-01",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": True,
                    "_bulk_attachments_present": True,
                    "_bulk_submission_complete": False,
                }
            }

        def fetch_assignment_submissions_bulk(self, **kwargs):
            return {}

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=ModuleBulkClient,
    )
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    assert client.module_calls == [(77, "assign")]
    assert client.fetch_calls == []
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["module_bulk_activities"] == 1
    assert summary["module_bulk_calls"] == 1
    assert summary["html_activities"] == 0


def test_snapshot_reuses_activity_index_shared_by_content_discovery():
    class SharedIndexClient(_IncrementalClient):
        def list_activities(self, *args, **kwargs):
            raise AssertionError("shared discovery should avoid a second index request")

    entry = _entry(1)
    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [entry]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=SharedIndexClient,
    )
    snapshots = _Snapshots()
    result = service.sync_snapshots(
        "owner",
        now=1,
        snapshots=snapshots,
        discovered=[
            {
                "course_id": "poo",
                "status": "found",
                "moodle_course_id": "77",
                "activity_candidates": [entry],
            }
        ],
    )

    assert result == {"updated": 1, "failed": 0, "failed_courses": []}
    assert any(event == "moodle_activity_index_reused" for event, _ in logs)


def test_module_bulk_ignores_activity_kinds_without_a_supported_service():
    class ModuleBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_submission_complete": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            raise AssertionError("unsupported activity kind must not call module bulk")

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, kind="page")]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=ModuleBulkClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    assert client.fetch_calls == [1]
    assert not any(event == "activity_snapshot_module_bulk_capture" for event, _ in logs)


@pytest.mark.parametrize("mode", ["shape", "missing"])
def test_module_bulk_failures_keep_the_html_fallback(mode):
    class ProbeClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_submission_complete": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            if mode == "shape":
                return []
            return {}

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=ProbeClient,
    )
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    assert client.fetch_calls == [1]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["module_bulk_failures"] == (1 if mode == "shape" else 0)
    assert any(
        event == "moodle_activity_module_bulk_detail_fallback" for event, _ in logs
    ) if mode == "missing" else any(
        event == "moodle_activity_module_bulk_unavailable" for event, _ in logs
    )


def test_empty_module_bulk_fields_skip_html_n_plus_one_when_all_ids_are_present():
    class EmptyModuleBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                str(source_id): {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
                for source_id in (1, 2)
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                str(source_id): {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
                for source_id in (1, 2)
            }

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, "quiz"), _entry(2, "quiz")]},
        lambda *, source_id, kind: {"description": "should not be fetched", "attachments": []},
        client_class=EmptyModuleBulkClient,
    )
    snapshots = _Snapshots()

    assert service.sync_snapshots("owner", now=1, snapshots=snapshots)["failed"] == 0
    assert client.fetch_calls == []
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["html_activities"] == 0
    assert summary["html_skipped_count"] == 2
    assert any(event == "moodle_activity_html_fallback_skipped" for event, _ in logs)


def test_empty_assignment_module_bulk_fields_skip_html_n_plus_one_when_all_ids_are_present():
    class EmptyModuleBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                str(source_id): {
                    "description": "",
                    "dates_text": "Vencimento: 2026-12-01",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
                for source_id in (1, 2)
            }

        def fetch_assignment_submissions_bulk(self, **kwargs):
            return {
                str(assignment_id): {
                    "submission_state": "not_submitted",
                    "submission_text": "Nenhum envio",
                    "_bulk_submission_complete": True,
                }
                for assignment_id in kwargs["assignment_ids"]
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                str(source_id): {
                    "description": "",
                    "dates_text": "Vencimento: 2026-12-01",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_assignment_id": 10_000 + source_id,
                }
                for source_id in (1, 2)
            }

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, "assign"), _entry(2, "assign")]},
        lambda *, source_id, kind: {
            "description": "should not be fetched",
            "attachments": [],
        },
        client_class=EmptyModuleBulkClient,
    )
    snapshots = _Snapshots()

    assert service.sync_snapshots("owner", now=1, snapshots=snapshots)["failed"] == 0
    assert client.fetch_calls == []
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["html_activities"] == 0
    assert summary["html_skipped_count"] == 2


def test_assignment_submission_bulk_keeps_html_for_missing_statuses() -> None:
    class PartialSubmissionClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            return {
                str(source_id): {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
                for source_id in (1, 2)
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_assignment_id": 10_001,
                },
                "2": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_assignment_id": 10_002,
                },
                "unexpected": None,
            }

        def fetch_assignment_submissions_bulk(self, **kwargs):
            assert kwargs["assignment_ids"] == [10_001, 10_002]
            return {
                "10001": {
                    "submission_state": "submitted",
                    "submission_text": "submitted",
                    "_bulk_submission_complete": True,
                }
            }

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, "assign"), _entry(2, "assign")]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=PartialSubmissionClient,
    )
    summary = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert summary["failed"] == 0
    assert client.fetch_calls == [2]
    fields = [item for event, item in logs if event == "activity_snapshots_synced"][-1]
    assert fields["submission_bulk_calls"] == 1
    assert fields["submission_bulk_statuses"] == 1


def test_assignment_submission_bulk_failure_keeps_the_html_fallback() -> None:
    class FailingSubmissionClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_assignment_id": 10_001,
                }
            }

        def fetch_assignment_submissions_bulk(self, **kwargs):
            return []

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, "assign")]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=FailingSubmissionClient,
    )
    assert service.sync_snapshots("owner", now=1, snapshots=_Snapshots())["failed"] == 0
    fields = [item for event, item in logs if event == "activity_snapshots_synced"][-1]
    assert fields["submission_bulk_failures"] == 1
    assert client.fetch_calls == [1]


def test_assignment_submission_bulk_failure_metadata_shape_keeps_html_fallback() -> None:
    class MalformedSubmissionClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_assignment_id": 10_001,
                }
            }

        def fetch_assignment_submissions_bulk(self, **kwargs):
            return {"_bulk_failed_assignment_ids": ["bad"]}

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1, "assign")]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=MalformedSubmissionClient,
    )
    assert service.sync_snapshots("owner", now=1, snapshots=_Snapshots())["failed"] == 0
    fields = [item for event, item in logs if event == "activity_snapshots_synced"][-1]
    assert fields["submission_bulk_failures"] == 1
    assert client.fetch_calls == [1]


def test_partial_module_bulk_fields_are_preserved_when_html_has_no_enrichment():
    class PartialModuleBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            return {
                "1": {
                    "description": "Descrição estruturada",
                    "dates_text": "Vencimento: 2026-12-01",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": True,
                    "_bulk_attachments_present": False,
                }
            }

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {
            "description": "",
            "dates_text": "",
            "has_due_date": False,
            "attachments": [],
        },
        client_class=PartialModuleBulkClient,
    )
    snapshots = _Snapshots()

    assert service.sync_snapshots("owner", now=1, snapshots=snapshots)["failed"] == 0
    saved = snapshots.saved["poo"]["activities"][0]
    assert saved["description"] == "Descrição estruturada"
    assert saved["dates_text"] == "Vencimento: 2026-12-01"
    assert saved["has_due_date"] is True
    assert client.fetch_calls == [1]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["html_activities"] == 1
    assert summary["html_skipped_count"] == 0


def test_module_bulk_capability_failure_is_cached_for_later_courses():
    class ProbeClient(_IncrementalClient):
        def __init__(self, index, fetch):
            super().__init__(index, fetch)
            self.module_calls: list[tuple[int, str]] = []

        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_submission_complete": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            self.module_calls.append((kwargs["course_id"], kwargs["kind"]))
            return {}

    courses = [_course("poo"), _course("mat")]
    service, client, logs = _build(
        courses,
        {"ELEpoo": [_entry(1)], "ELEmat": [_entry(1)]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=ProbeClient,
    )
    snapshots = _Snapshots()
    result = service.sync_snapshots(
        "owner",
        now=1,
        snapshots=snapshots,
        discovered=[
            {
                "course_id": "poo",
                "course_code": "ELEpoo",
                "term": "2026-2",
                "moodle_course_id": "77",
                "status": "found",
                "candidates": [],
                "activity_candidates": [_entry(1)],
            },
            {
                "course_id": "mat",
                "course_code": "ELEmat",
                "term": "2026-2",
                "moodle_course_id": "78",
                "status": "found",
                "candidates": [],
                "activity_candidates": [_entry(1)],
            },
        ],
    )

    assert result["failed"] == 0
    assert client.module_calls == [(77, "assign")]
    skipped = [fields for event, fields in logs if event == "moodle_activity_module_bulk_skipped"]
    assert skipped and skipped[-1]["moodle_course_id"] == 78


def test_empty_module_bulk_payload_is_scoped_to_each_course():
    class EmptyPayloadClient(_IncrementalClient):
        def __init__(self, index, fetch):
            super().__init__(index, fetch)
            self.module_calls: list[tuple[int, str]] = []

        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

        def fetch_course_activity_module_bulk(self, **kwargs):
            self.module_calls.append((kwargs["course_id"], kwargs["kind"]))
            return {
                "1": {
                    "description": "",
                    "dates_text": "Vencimento: 2026-12-01",
                    "has_due_date": True,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

    courses = [_course("poo"), _course("mat")]
    service, client, logs = _build(
        courses,
        {"ELEpoo": [_entry(1, "quiz")], "ELEmat": [_entry(1, "quiz")]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=EmptyPayloadClient,
    )
    snapshots = _Snapshots()
    result = service.sync_snapshots(
        "owner",
        now=1,
        snapshots=snapshots,
        discovered=[
            {
                "course_id": "poo",
                "course_code": "ELEpoo",
                "term": "2026-2",
                "moodle_course_id": "77",
                "status": "found",
                "candidates": [],
                "activity_candidates": [_entry(1, "quiz")],
            },
            {
                "course_id": "mat",
                "course_code": "ELEmat",
                "term": "2026-2",
                "moodle_course_id": "78",
                "status": "found",
                "candidates": [],
                "activity_candidates": [_entry(1, "quiz")],
            },
        ],
    )

    assert result["failed"] == 0
    assert client.module_calls == [(77, "quiz"), (78, "quiz")]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["html_activities"] == 0
    assert summary["html_skipped_count"] == 2
    for course_id in ("poo", "mat"):
        saved = next(
            activity
            for activity in snapshots.saved[course_id]["activities"]
            if activity["source_id"] == "1"
        )
        assert saved["dates_text"] == "Vencimento: 2026-12-01"
        assert saved["has_due_date"] is True


def test_module_bulk_skips_when_tokens_are_not_usable():
    class ProbeClient(_IncrementalClient):
        def fetch_course_activity_module_bulk(self, **kwargs):
            raise AssertionError("module endpoint should not be called")

        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {}

    service, client, _ = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=ProbeClient,
    )
    service._tokens.load = lambda *args, **kwargs: SimpleNamespace(
        term="2026-2", webservice_token=1, private_token=None
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    assert client.fetch_calls == [1]


def _build(
    courses,
    index,
    fetch,
    *,
    max_workers=DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY,
    update_workers=1,
    logs=None,
    client_class=_Client,
):
    logs = [] if logs is None else logs
    client = client_class(index, fetch)
    course_map = {course["id"]: course for course in courses}
    service = CourseActivityService(
        SimpleNamespace(
            get_course=lambda course_id: course_map[course_id],
            list_courses=lambda: list(courses),
        ),
        SimpleNamespace(
            list_catalog=lambda _courses: [{"status": "found", "moodle_course_id": "77"}]
        ),
        SimpleNamespace(load=lambda user_id, *, now: SimpleNamespace(token="token-safe")),
        client,
        SimpleNamespace(
            load=lambda *args, **kwargs: SimpleNamespace(
                term="2026-2", webservice_token="w" * 32, private_token="p" * 32
            )
        ),
        telemetry=lambda event, fields: logs.append((event, dict(fields))),
        max_workers=max_workers,
        update_workers=update_workers,
    )
    return service, client, logs


def _bare_service(max_workers=None, update_workers=None) -> CourseActivityService:
    kwargs = {} if max_workers is None else {"max_workers": max_workers}
    if update_workers is not None:
        kwargs["update_workers"] = update_workers
    return CourseActivityService(
        SimpleNamespace(
            get_course=lambda _course_id: _course("poo"),
            list_courses=lambda: [_course("poo")],
        ),
        SimpleNamespace(
            list_catalog=lambda _courses: [{"status": "found", "moodle_course_id": "77"}]
        ),
        SimpleNamespace(load=lambda *args, **kwargs: SimpleNamespace(token="token-safe")),
        SimpleNamespace(
            list_activities=lambda *args, **kwargs: [],
            fetch_activity=lambda *args, **kwargs: {},
        ),
        SimpleNamespace(load=lambda *args, **kwargs: None),
        **kwargs,
    )


def test_concurrent_capture_preserves_index_order_despite_out_of_order_completion():
    courses = [_course("poo")]
    entries = [_entry(i) for i in range(1, 9)]
    index = {"ELEpoo": entries}

    def fetch(*, source_id, kind):
        # Earlier indexes sleep longer, so completion order is reversed.
        time.sleep(0.06 * (len(entries) - source_id + 1) / len(entries))
        return {"description": f"detail {source_id}", "attachments": []}

    service, client, logs = _build(courses, index, fetch, max_workers=4)
    snapshots = _Snapshots()
    result = service.sync_snapshots("owner", now=1793188800, snapshots=snapshots)
    assert result == {"updated": 1, "failed": 0, "failed_courses": []}
    assert sorted(client.fetch_calls) == list(range(1, 9))
    saved = snapshots.saved["poo"]
    assert [a["source_id"] for a in saved["activities"]] == [str(i) for i in range(1, 9)]
    assert [a["description"] for a in saved["activities"]] == [f"detail {i}" for i in range(1, 9)]
    assert all(a["files"] == [] and a["term"] == "2026-2" for a in saved["activities"])
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["total_courses"] == 1
    assert summary["updated"] == 1
    assert summary["failed"] == 0
    assert summary["failed_activities"] == 0
    assert summary["concurrency"] == 4
    assert isinstance(summary["duration_ms"], int)
    assert "reused" not in summary


def test_first_sync_uses_one_course_bulk_read_instead_of_one_html_request_per_activity():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2), _entry(3, kind="quiz")]}

    service, client, logs = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()

    result = service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.bulk_calls == [77]
    assert client.fetch_calls == []
    assert [item["description"] for item in snapshots.saved["poo"]["activities"]] == [
        "bulk detail 1",
        "bulk detail 2",
        "bulk detail 3",
    ]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["bulk_activities"] == 3
    assert summary["bulk_submission_unknown"] == 3
    assert summary["bulk_fallbacks"] == 0
    assert summary["html_activities"] == 0


def test_incremental_sync_reuses_snapshot_when_moodle_reports_no_changes():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2)]}
    service, client, _ = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.fetch_calls.clear()
    client.bulk_calls.clear()
    client.changed_ids = set()

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.update_calls[-1] == 1_793_188_800
    assert client.bulk_calls == []
    assert client.fetch_calls == []


def test_force_sync_skips_change_probes_and_refreshes_through_bulk_path():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2)]}
    service, client, logs = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.update_calls.clear()
    client.bulk_calls.clear()
    client.fetch_calls.clear()
    service._force = True

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.update_calls == []
    assert client.bulk_calls == [77]
    assert client.fetch_calls == []
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["force"] is True
    assert summary["updates_checked"] == 0
    assert summary["bulk_activities"] == 2


def test_incremental_sync_bulk_reads_only_modules_reported_as_changed():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2), _entry(3)]}
    service, client, logs = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.bulk_calls.clear()
    client.fetch_calls.clear()
    client.changed_ids = {2}

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.bulk_calls == [77]
    assert client.fetch_calls == []
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["reused_activities"] == 2
    assert summary["bulk_activities"] == 1
    assert summary["updates_changed"] == 1


def test_incremental_sync_checks_each_metaturma_course():
    class MetaturmaClient(_IncrementalClient):
        def activity_updates_since(self, token, *, term, course_id, since):
            self.update_calls.append(since)
            self.update_course_ids.append(course_id)
            return {2} if course_id == 88 else set()

    first = _entry(1)
    second = _entry(2)
    second["moodle_course_id"] = "88"
    index = {"ELEpoo": [first, second]}
    service, client, logs = _build(
        [_course("poo")],
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=MetaturmaClient,
        update_workers=2,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.bulk_calls.clear()

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.update_course_ids[-2:] == [77, 88]
    assert client.bulk_calls == [88]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["updates_checked"] == 2
    assert summary["updates_changed"] == 1


def test_bulk_omissions_fall_back_to_html_without_persisting_private_flags():
    class IncompleteBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "_bulk_submission_complete": False,
                }
            }

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {
            "description": "HTML instructions",
            "dates_text": "Vencimento: 2026-12-01",
            "has_due_date": True,
            "submission_state": "not_submitted",
            "submission_text": "Nenhum envio",
            "attachments": [{"name": "enunciado.pdf", "url": "https://moodle/file"}],
        },
        client_class=IncompleteBulkClient,
    )
    snapshots = _Snapshots()

    result = service.sync_snapshots("owner", now=1, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.fetch_calls == [1]
    saved = snapshots.saved["poo"]["activities"][0]
    assert saved["description"] == "HTML instructions"
    assert not any(key.startswith("_bulk_") for key in saved)
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["bulk_fallbacks"] == 1
    assert summary["html_activities"] == 1
    fallback = next(
        fields for event, fields in logs if event == "moodle_activity_bulk_detail_fallback"
    )
    assert fallback["source_id"] == "1"
    assert fallback["missing_fields"] == ["description", "attachments"]
    html_result = next(
        fields for event, fields in logs if event == "moodle_activity_html_detail_result"
    )
    assert html_result["outcome"] == "complete"
    assert html_result["fallback_reason"] == "missing_bulk_fields"
    assert html_result["description_chars"] == len("HTML instructions")
    assert html_result["attachment_count"] == 1
    assert snapshots.saved["poo"]["activities"][0].get("_html_response_bytes") is None


def test_html_detail_quality_normalizes_invalid_metadata_and_allowlisted_empty_fields():
    quality = activities_module._html_detail_quality(
        {
            "description": "text",
            "attachments": [{"name": "file"}],
            "_html_description_chars": -1,
            "_html_attachment_count": "invalid",
            "_html_empty_fields": ["attachments", "ignored"],
            "_html_response_status": 700,
            "_html_response_bytes": -1,
        }
    )

    assert quality == {
        "response_status": 200,
        "response_bytes": None,
        "description_chars": 4,
        "attachment_count": 1,
        "empty_fields": ["attachments"],
        "outcome": "partial",
        "metadata_source": "client",
    }
    complete = activities_module._html_detail_quality(
        {
            "description": "text",
            "attachments": [{"name": "file"}],
            "_html_description_chars": 4,
            "_html_attachment_count": 1,
            "_html_empty_fields": [],
            "_html_response_status": 200,
            "_html_response_bytes": 42,
        }
    )
    assert complete["outcome"] == "complete"
    assert complete["metadata_source"] == "client"


def test_bulk_failure_records_reason_for_the_following_html_fallback():
    class BrokenBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            raise InvalidMoodleResponse("course_activity_bulk_shape")

    service, _client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "HTML", "attachments": []},
        client_class=BrokenBulkClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    html_result = next(
        fields for event, fields in logs if event == "moodle_activity_html_detail_result"
    )
    assert html_result["fallback_reason"] == "bulk_unavailable"


def test_non_mapping_html_detail_is_reported_as_a_failed_fallback():
    class IncompleteBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

    service, _client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: [],
        client_class=IncompleteBulkClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 1
    html_result = next(
        fields for event, fields in logs if event == "moodle_activity_html_detail_result"
    )
    assert html_result["outcome"] == "failed"
    assert html_result["error_reason"] == "activity_page_shape"


@pytest.mark.parametrize(
    ("detail", "expected_outcome", "expected_empty"),
    [
        ({"description": "", "attachments": []}, "empty_fields", ["description", "attachments"]),
        ({"description": "Only text", "attachments": []}, "partial", ["attachments"]),
    ],
)
def test_html_fallback_reports_empty_fields_as_quality_not_failure(
    detail, expected_outcome, expected_empty
):
    class IncompleteBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

    service, _client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: detail,
        client_class=IncompleteBulkClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    html_result = next(
        fields for event, fields in logs if event == "moodle_activity_html_detail_result"
    )
    assert html_result["outcome"] == expected_outcome
    assert html_result["empty_fields"] == expected_empty
    summary = next(fields for event, fields in logs if event == "activity_snapshots_synced")
    assert summary["html_quality_counts"][expected_outcome] == 1


def test_html_fallback_failure_is_distinguished_from_empty_html_fields():
    class IncompleteBulkClient(_IncrementalClient):
        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            return {
                "1": {
                    "description": "",
                    "dates_text": "",
                    "has_due_date": False,
                    "submission_state": "unknown",
                    "submission_text": "",
                    "attachments": [],
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                }
            }

    def failing_fetch(*, source_id, kind):
        raise InvalidMoodleResponse(
            "activity_page_shape", details={"response_status": 200, "response_bytes": 3}
        )

    service, _client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        failing_fetch,
        client_class=IncompleteBulkClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 1
    html_result = next(
        fields for event, fields in logs if event == "moodle_activity_html_detail_result"
    )
    assert html_result["outcome"] == "failed"
    assert html_result["error_reason"] == "activity_page_shape"
    assert html_result["response_status"] == 200
    assert html_result["response_bytes"] == 3


def test_incomplete_bulk_capability_skips_the_extra_request():
    class IncompleteBulkCapabilityClient(_IncrementalClient):
        bulk_activity_details_complete = False

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {
            "description": "HTML instructions",
            "dates_text": "",
            "has_due_date": False,
            "submission_state": "not_submitted",
            "submission_text": "Nenhum envio",
            "attachments": [],
        },
        client_class=IncompleteBulkCapabilityClient,
    )

    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())

    assert result["failed"] == 0
    assert client.bulk_calls == []
    assert client.fetch_calls == [1]
    assert any(event == "moodle_activity_bulk_skipped" for event, _ in logs)


def test_bulk_miss_falls_back_only_for_the_missing_changed_activity():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2)]}
    service, client, logs = _build(
        courses,
        index,
        lambda *, source_id, kind: {
            "description": f"html detail {source_id}",
            "dates_text": "",
            "has_due_date": False,
            "submission_state": "unknown",
            "submission_text": "",
            "attachments": [],
        },
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.changed_ids = {2}
    client.bulk_result = {}

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.fetch_calls == [2]
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["reused_activities"] == 1
    assert summary["bulk_activities"] == 0
    assert summary["bulk_fallbacks"] == 1
    assert summary["html_activities"] == 1
    fallback = next(
        fields for event, fields in logs if event == "moodle_activity_bulk_detail_fallback"
    )
    assert fallback["reason"] == "activity_missing_from_bulk_response"


def test_failed_change_probe_refreshes_all_through_bulk_path():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2)]}
    service, client, _ = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.fail_updates = True
    client.bulk_calls.clear()

    result = service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)

    assert result["failed"] == 0
    assert client.bulk_calls == [77]
    assert client.fetch_calls == []


def test_incremental_helpers_reject_invalid_snapshots_and_timestamps():
    snapshots = _Snapshots()
    snapshots.saved["poo"] = {"term": "2026-2", "activities": [None]}
    assert activities_module._load_previous_snapshot(snapshots, "poo", "2026-2") is None
    assert activities_module._snapshot_epoch({}) is None
    assert activities_module._snapshot_epoch({"synced_at": "not-a-date"}) is None
    assert activities_module._snapshot_epoch({"synced_at": "1960-01-01T00:00:00Z"}) is None
    assert activities_module._metric({}, "missing") == 0
    assert activities_module._metric({"count": "bad"}, "count") == 0
    with pytest.raises(InvalidMoodleResponse):
        activities_module._entry_moodle_course_id({"moodle_course_id": "bad"}, "77")
    with pytest.raises(InvalidMoodleResponse):
        activities_module._entry_moodle_course_id({"moodle_course_id": "0"}, "77")


def test_empty_descriptions_are_rechecked_after_the_bounded_reuse_window():
    complete = {
        "description": "",
        "dates_text": "",
        "has_due_date": False,
        "submission_state": "unknown",
        "submission_text": "",
        "attachments": [],
    }

    assert activities_module._detail_can_be_reused(complete, snapshot_epoch=1, now=1)
    assert activities_module._detail_can_be_reused(
        complete,
        snapshot_epoch=1,
        now=1 + activities_module.EMPTY_DESCRIPTION_RECHECK_SECONDS - 1,
    )
    assert not activities_module._detail_can_be_reused(
        complete,
        snapshot_epoch=1,
        now=1 + activities_module.EMPTY_DESCRIPTION_RECHECK_SECONDS,
    )
    assert not activities_module._detail_can_be_reused(complete, snapshot_epoch=None, now=1)
    assert not activities_module._detail_can_be_reused({"description": ""}, snapshot_epoch=1, now=1)


def test_assignment_submission_details_are_rechecked_after_a_bounded_window():
    complete_assignment = {
        "kind": "assignment",
        "description": "Instructions are visible",
        "dates_text": "",
        "has_due_date": False,
        "submission_state": "not_submitted",
        "submission_text": "Nenhum envio",
        "attachments": [],
    }

    assert activities_module._detail_can_be_reused(complete_assignment, snapshot_epoch=1, now=1)
    assert activities_module._detail_can_be_reused(
        complete_assignment,
        snapshot_epoch=1,
        now=1 + activities_module.SUBMISSION_RECHECK_SECONDS - 1,
    )
    assert not activities_module._detail_can_be_reused(
        complete_assignment,
        snapshot_epoch=1,
        now=1 + activities_module.SUBMISSION_RECHECK_SECONDS,
    )
    assert not activities_module._detail_can_be_reused(
        complete_assignment,
        snapshot_epoch=2,
        now=1,
    )

    # Quizzes do not use the assignment submission-status path.
    quiz = {**complete_assignment, "kind": "quiz"}
    assert activities_module._detail_can_be_reused(
        quiz,
        snapshot_epoch=1,
        now=1 + activities_module.SUBMISSION_RECHECK_SECONDS,
    )


def test_token_store_failure_falls_back_to_html_and_is_observable():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1)]}
    service, client, logs = _build(
        courses,
        index,
        lambda *, source_id, kind: {"description": "html", "attachments": []},
    )

    def fail_load(*args, **kwargs):
        raise MoodleTokenStoreUnavailable("store unavailable")

    service._tokens = SimpleNamespace(load=fail_load)
    assert service.sync_snapshots("owner", now=1, snapshots=_Snapshots())["failed"] == 0
    assert any(event == "moodle_activity_bulk_unavailable" for event, _ in logs)


def test_policy_result_without_capture_metrics_does_not_break_summary():
    service, _, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "unused", "attachments": []},
    )

    class NullPolicy:
        def state(self, course_id, source):
            return {}

        def run(self, *args, **kwargs):
            return None, False

    service._policy = NullPolicy()
    assert service.sync_snapshots("owner", now=1, snapshots=_Snapshots())["updated"] == 1
    summary = [fields for event, fields in logs if event == "activity_snapshots_synced"][-1]
    assert summary["bulk_activities"] == 0


def test_invalid_previous_timestamp_refreshes_all_incremental_entries():
    service, client, _ = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1), _entry(2)]},
        lambda *, source_id, kind: {"description": "unused", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    snapshots.saved["poo"] = {
        "course_id": "poo",
        "term": "2026-2",
        "synced_at": "invalid",
        "activities": [],
    }
    service.sync_snapshots("owner", now=1, snapshots=snapshots)
    assert client.bulk_calls == [77]


def test_invalid_update_shape_falls_back_to_bulk_refresh():
    class BadUpdatesClient(_IncrementalClient):
        def activity_updates_since(self, token, *, term, course_id, since):
            self.update_calls.append(since)
            return [2]

    service, client, _ = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1), _entry(2)]},
        lambda *, source_id, kind: {"description": "unused", "attachments": []},
        client_class=BadUpdatesClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client.bulk_calls.clear()
    service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)
    assert client.bulk_calls == [77]


def test_new_index_entry_takes_the_non_reused_update_branch():
    service, client, _ = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1), _entry(2)]},
        lambda *, source_id, kind: {"description": "unused", "attachments": []},
        client_class=_IncrementalClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1_793_188_800, snapshots=snapshots)
    client._index["ELEpoo"].append(_entry(3))
    client.changed_ids = {3}
    client.bulk_calls.clear()
    service.sync_snapshots("owner", now=1_793_188_900, snapshots=snapshots)
    assert client.bulk_calls == [77]


def test_invalid_mobile_token_shape_skips_bulk_without_failing_sync():
    service, client, _ = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {"description": "html", "attachments": []},
        client_class=_IncrementalClient,
    )
    service._tokens = SimpleNamespace(
        load=lambda *args, **kwargs: SimpleNamespace(
            term="2026-2", webservice_token=1, private_token=None
        )
    )
    snapshots = _Snapshots()
    assert service.sync_snapshots("owner", now=1, snapshots=snapshots)["failed"] == 0
    assert client.bulk_calls == []
    assert client.fetch_calls == [1]


def test_bulk_invalid_payload_and_exception_fall_back_to_html():
    class BadBulkClient(_IncrementalClient):
        mode = "shape"

        def fetch_course_activity_bulk(self, **kwargs):
            self.bulk_calls.append(kwargs["course_id"])
            if self.mode == "shape":
                return []
            raise MoodleUnavailable("bulk unavailable", upstream_status=503)

    service, client, logs = _build(
        [_course("poo")],
        {"ELEpoo": [_entry(1)]},
        lambda *, source_id, kind: {
            "description": "html",
            "dates_text": "",
            "has_due_date": False,
            "submission_state": "unknown",
            "submission_text": "",
            "attachments": [],
        },
        client_class=BadBulkClient,
    )
    snapshots = _Snapshots()
    service.sync_snapshots("owner", now=1, snapshots=snapshots)
    client.mode = "error"
    service.sync_snapshots("owner", now=2, snapshots=_Snapshots())
    assert client.fetch_calls == [1, 1]
    assert sum(event == "moodle_activity_bulk_unavailable" for event, _ in logs) >= 2


def test_partial_failure_attempts_every_activity_and_preserves_the_previous_snapshot():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2), _entry(3, kind="quiz")]}

    def fetch(*, source_id, kind):
        if source_id == 1:
            raise InvalidMoodleResponse("activity_page_shape", details={"upstream_status": 500})
        if source_id == 3:
            raise MoodleUnavailable("rate limited", upstream_status=429)
        return {"description": "ok", "attachments": []}

    service, client, logs = _build(courses, index, fetch, max_workers=2)
    snapshots = _Snapshots()
    previous = {
        "course_id": "poo",
        "term": "2026-2",
        "synced_at": "2026-01-01T00:00:00Z",
        "activities": [_entry(1)],
    }
    snapshots.saved["poo"] = copy.deepcopy(previous)
    result = service.sync_snapshots("owner", now=1793188800, snapshots=snapshots)
    # No task is cancelled on the first failure: all activities were attempted.
    assert sorted(client.fetch_calls) == [1, 2, 3]
    assert result["failed"] == 1 and result["updated"] == 0
    issue = result["failed_courses"][0]
    assert issue["course_id"] == "poo"
    assert issue["reason"] == "activity_page_shape"
    assert issue["retained_previous"] is True
    # The previous valid snapshot is never replaced by empty/partial data.
    assert snapshots.saved["poo"] == previous
    assert not any(
        event == "academic_sync_stage_completed"
        and fields.get("stage") == "activity_snapshot_persist"
        for event, fields in logs
    )
    failures = [f for e, f in logs if e == "activity_snapshot_activity_failed"]
    assert len(failures) == 2
    by_source = {f["source_id"]: f for f in failures}
    first = by_source["1"]
    assert first["course_id"] == "poo"
    assert first["course_code"] == "ELEpoo"
    assert first["term"] == "2026-2"
    assert first["kind"] == "assign"
    assert first["reason"] == "activity_page_shape"
    assert first["exception_type"] == "InvalidMoodleResponse"
    assert first["upstream_class"] == "http_500"
    assert first["upstream_status"] == 500
    assert first["attempt"] == 1
    assert isinstance(first["duration_ms"], int)
    second = by_source["3"]
    assert second["kind"] == "quiz"
    assert second["reason"] == "MoodleUnavailable"
    assert second["exception_type"] == "MoodleUnavailable"
    assert second["upstream_class"] == "http_429"
    assert second["upstream_status"] == 429
    assert "detail" not in str(failures) and "token-safe" not in str(failures)
    summary = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert summary["failed"] == 1 and summary["failed_activities"] == 2
    assert summary["concurrency"] == 2 and summary["total_courses"] == 1
    assert summary["html_quality_counts"] == {"partial": 1, "failed": 2}
    assert summary["html_empty_field_counts"] == {"attachments": 1}


def test_capture_raises_one_course_level_failure_with_count_and_first_reason():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2), _entry(3)]}

    def fetch(*, source_id, kind):
        if source_id in (1, 3):
            raise InvalidMoodleResponse("activity_page_shape")
        return {"description": "ok", "attachments": []}

    service, client, logs = _build(courses, index, fetch, max_workers=2)
    snapshots = _Snapshots()
    with pytest.raises(ActivitySnapshotCaptureFailed) as captured:
        service._capture_snapshot("owner", courses[0], 1793188800, snapshots)
    assert captured.value.failed_count == 2
    assert captured.value.first_reason == "activity_page_shape"
    assert snapshots.saved == {}


def test_timeout_failure_is_classified_as_timeout_and_not_masked():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1), _entry(2)]}

    def fetch(*, source_id, kind):
        raise MoodleUnavailable("slow upstream", timed_out=True)

    service, client, logs = _build(courses, index, fetch, max_workers=2)
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert result["failed"] == 1 and result["updated"] == 0
    failures = [f for e, f in logs if e == "activity_snapshot_activity_failed"]
    assert len(failures) == 2
    for failure in failures:
        assert failure["upstream_class"] == "timeout"
        assert failure["exception_type"] == "MoodleUnavailable"
        assert failure["reason"] == "MoodleUnavailable"
        assert "upstream_status" not in failure
        assert failure["attempt"] == 1


def test_unexpected_error_is_classified_as_error_not_success():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1)]}

    def fetch(*, source_id, kind):
        raise ValueError("boom")

    service, client, logs = _build(courses, index, fetch, max_workers=1)
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert result["failed"] == 1
    failure = next(f for e, f in logs if e == "activity_snapshot_activity_failed")
    assert failure["upstream_class"] == "error"
    assert failure["reason"] == "ValueError"
    assert failure["exception_type"] == "ValueError"
    assert "upstream_status" not in failure


def test_one_failing_course_does_not_block_other_courses():
    courses = [_course("poo"), _course("mat")]
    index = {"ELEpoo": [_entry(1), _entry(2)], "ELEmat": [_entry(5)]}

    def fetch(*, source_id, kind):
        if source_id in (1, 2):
            raise MoodleUnavailable("maintenance")
        return {"description": "ok", "attachments": []}

    service, client, logs = _build(courses, index, fetch, max_workers=4)
    snapshots = _Snapshots()
    result = service.sync_snapshots("owner", now=1, snapshots=snapshots)
    assert result["updated"] == 1 and result["failed"] == 1
    assert set(snapshots.saved) == {"mat"}
    assert result["failed_courses"][0]["course_id"] == "poo"
    assert result["failed_courses"][0]["retained_previous"] is True
    summary = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert summary["total_courses"] == 2
    assert summary["updated"] == 1 and summary["failed"] == 1
    assert summary["failed_activities"] == 2


def test_failed_courses_list_is_capped_while_the_count_stays_exact():
    courses = [_course(f"c{i}") for i in range(25)]
    index = {course["code"]: [_entry(1)] for course in courses}

    def fetch(*, source_id, kind):
        raise MoodleUnavailable("down")

    service, client, logs = _build(courses, index, fetch, max_workers=4)
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert result["failed"] == 25
    assert len(result["failed_courses"]) == 20


@pytest.mark.parametrize("workers", [1, 3])
def test_pool_never_exceeds_the_configured_max_workers(workers):
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(i) for i in range(1, 13)]}
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fetch(*, source_id, kind):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.02)
        with lock:
            in_flight -= 1
        return {"description": f"detail {source_id}", "attachments": []}

    service, client, logs = _build(courses, index, fetch, max_workers=workers)
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert result["updated"] == 1 and result["failed"] == 0
    assert len(client.fetch_calls) == 12
    assert peak == workers
    summary = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert summary["concurrency"] == workers


@pytest.mark.parametrize(
    ("max_workers", "expected"),
    [
        (-3, MIN_ACTIVITY_SNAPSHOT_CONCURRENCY),
        (0, MIN_ACTIVITY_SNAPSHOT_CONCURRENCY),
        (1, 1),
        (4, 4),
        (8, MAX_ACTIVITY_SNAPSHOT_CONCURRENCY),
        (99, MAX_ACTIVITY_SNAPSHOT_CONCURRENCY),
    ],
)
def test_constructor_clamps_max_workers_into_bounds(max_workers, expected):
    assert _bare_service(max_workers)._max_workers == expected


def test_default_max_workers_is_the_conservative_default():
    assert _bare_service()._max_workers == DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY == 8


def test_constructor_rejects_invalid_update_worker_count():
    with pytest.raises(ValueError, match="invalid activity update concurrency"):
        _bare_service(update_workers=0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("", DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("   ", DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("abc", DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("4.5", DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("0", MIN_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("-7", MIN_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("1", 1),
        ("3", 3),
        ("8", MAX_ACTIVITY_SNAPSHOT_CONCURRENCY),
        ("999", MAX_ACTIVITY_SNAPSHOT_CONCURRENCY),
    ],
)
def test_env_concurrency_parsing_is_safe_and_bounded(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("MOODLE_ACTIVITY_SNAPSHOT_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("MOODLE_ACTIVITY_SNAPSHOT_CONCURRENCY", raw)
    assert function._activity_snapshot_max_workers() == expected


def test_main_wires_the_env_concurrency_into_the_activity_service(monkeypatch):
    monkeypatch.setattr(function, "_moodle_token_store", lambda *a, **k: object())
    monkeypatch.setattr(function, "_moodle_material_catalog_repository", lambda *a, **k: object())
    monkeypatch.setenv("MOODLE_ACTIVITY_SNAPSHOT_CONCURRENCY", "6")
    service = function._course_activity_service(
        {}, "user", courses=object(), sessions=object(), client=object()
    )
    assert service._max_workers == 6
    monkeypatch.setenv("MOODLE_ACTIVITY_SNAPSHOT_CONCURRENCY", "not-a-number")
    service = function._course_activity_service(
        {}, "user", courses=object(), sessions=object(), client=object()
    )
    assert service._max_workers == DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY


class _FakeResponse:
    def __init__(self, body, url, *, content_type="text/html; charset=utf-8"):
        self._body = body
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, limit):
        return self._body

    def geturl(self):
        return self._url


class _FakeOpener:
    def __init__(self, responses, *, delay=0.0):
        self.responses = list(responses)
        self.requests: list[object] = []
        self._lock = threading.Lock()
        self._delay = delay

    def open(self, request, *, timeout):
        with self._lock:
            self.requests.append(request)
            response = self.responses.pop(0)
        if self._delay:
            time.sleep(self._delay)
        if isinstance(response, BaseException):
            raise response
        return response


def _idp() -> _FakeResponse:
    page = (
        b'<form method="post" action="https://virtual.ufmg.br/samlsso">'
        b'<input type="hidden" name="RelayState" value="relay-safe">'
        b'<input type="hidden" name="SAMLResponse" value="assertion-safe">'
        b"</form>"
    )
    return _FakeResponse(page, "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO")


def _moodle_dashboard() -> _FakeResponse:
    body = b'<script>M.cfg={"sesskey":"session-key-123"};</script>'
    return _FakeResponse(body, "https://virtual.ufmg.br/20262/my/")


def test_concurrent_connect_shares_one_saml_connection():
    opener = _FakeOpener([_idp(), _moodle_dashboard()], delay=0.05)
    client = MoodleStructuredDatesClient(opener=opener)
    results: list[tuple[str, str, str]] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            results.append(client._connect("token-safe", "2026-2"))
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(results) == 8
    assert all(result == results[0] for result in results)
    assert client.connection_count == 1
    assert len(opener.requests) == 2


def test_connect_rebuilds_the_connection_when_the_token_changes():
    opener = _FakeOpener([_idp(), _moodle_dashboard(), _idp(), _moodle_dashboard()])
    client = MoodleStructuredDatesClient(opener=opener)
    first = client._connect("token-one", "2026-2")
    second = client._connect("token-two", "2026-2")
    assert first == second
    assert client.connection_count == 2
    assert len(opener.requests) == 4


def _activity_client(responses) -> MoodleStructuredDatesClient:
    return MoodleStructuredDatesClient(opener=_FakeOpener(responses))


def test_http_error_is_classified_with_its_upstream_status():
    error = HTTPError(
        "https://virtual.ufmg.br/20262/mod/assign/view.php?id=7",
        429,
        "too many requests",
        Message(),
        None,
    )
    client = _activity_client([_idp(), _moodle_dashboard(), error])
    with pytest.raises(MoodleUnavailable) as captured:
        client.fetch_activity("token-safe", term="2026-2", source_id=7, kind="assign")
    assert captured.value.upstream_status == 429
    assert captured.value.timed_out is False


def test_timeout_error_is_classified_as_timeout():
    client = _activity_client([_idp(), _moodle_dashboard(), TimeoutError("timed out")])
    with pytest.raises(MoodleUnavailable) as captured:
        client.fetch_activity("token-safe", term="2026-2", source_id=7, kind="assign")
    assert captured.value.timed_out is True
    assert captured.value.upstream_status is None


def test_wrapped_url_timeout_is_also_classified_as_timeout():
    client = _activity_client([_idp(), _moodle_dashboard(), URLError(TimeoutError("timed out"))])
    with pytest.raises(MoodleUnavailable) as captured:
        client.fetch_activity("token-safe", term="2026-2", source_id=7, kind="assign")
    assert captured.value.timed_out is True
    assert captured.value.upstream_status is None


def test_plain_network_error_stays_unavailable_without_a_status():
    client = _activity_client([_idp(), _moodle_dashboard(), URLError(OSError("reset"))])
    with pytest.raises(MoodleUnavailable) as captured:
        client.fetch_activity("token-safe", term="2026-2", source_id=7, kind="assign")
    assert captured.value.timed_out is False
    assert captured.value.upstream_status is None


def test_moodle_unavailable_kwargs_are_optional_and_backwards_compatible():
    plain = MoodleUnavailable()
    assert plain.upstream_status is None
    assert plain.timed_out is False
    assert str(plain) == "Moodle is unavailable"
    custom = MoodleUnavailable("maintenance")
    assert str(custom) == "maintenance"
    assert custom.upstream_status is None and custom.timed_out is False


def test_index_failure_is_reported_with_its_parser_reason_and_no_activity_attempts():
    courses = [_course("poo")]
    index = {"ELEpoo": [_entry(1)]}

    def fetch(*, source_id, kind):
        raise AssertionError("fetch must not run when the index fails")

    service, client, logs = _build(courses, index, fetch, max_workers=4)

    def broken_index(token, *, term, course_id, course_code):
        raise InvalidMoodleResponse("course_activity_index_shape")

    client.list_activities = broken_index
    result = service.sync_snapshots("owner", now=1, snapshots=_Snapshots())
    assert result["failed"] == 1 and result["updated"] == 0
    issue = result["failed_courses"][0]
    assert issue["reason"] == "course_activity_index_shape"
    assert issue["retained_previous"] is True
    assert client.fetch_calls == []
    summary = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert summary["failed"] == 1 and summary["failed_activities"] == 0


def test_nine_courses_111_activities_before_after_timing_fixture():
    """Representative fixture (9 courses / 111 activities, fake Moodle latency).

    Records a before/after timing comparison: the legacy sequential capture
    (max_workers=1) versus the bounded pool (max_workers=4). Both runs must
    persist identical snapshots; the bounded run must be clearly faster.
    """
    per_course = [12, 12, 12, 12, 12, 12, 12, 12, 15]
    assert len(per_course) == 9 and sum(per_course) == 111
    courses = [_course(f"c{i}") for i in range(9)]
    index = {
        courses[i]["code"]: [_entry(1000 * i + j) for j in range(count)]
        for i, count in enumerate(per_course)
    }
    latency = 0.02

    def fetch(*, source_id, kind):
        time.sleep(latency)
        return {"description": f"detail {source_id}", "attachments": []}

    sequential_service, _, sequential_logs = _build(
        courses, index, fetch, max_workers=1
    )
    sequential_started = time.monotonic()
    sequential_result = sequential_service.sync_snapshots(
        "owner", now=1793188800, snapshots=_Snapshots()
    )
    sequential_seconds = time.monotonic() - sequential_started

    bounded_service, _, bounded_logs = _build(courses, index, fetch, max_workers=4)
    bounded_started = time.monotonic()
    bounded_result = bounded_service.sync_snapshots(
        "owner", now=1793188800, snapshots=_Snapshots()
    )
    bounded_seconds = time.monotonic() - bounded_started

    assert sequential_result["updated"] == 9 and sequential_result["failed"] == 0
    assert bounded_result == sequential_result
    sequential_summary = next(
        f for e, f in sequential_logs if e == "activity_snapshots_synced"
    )
    bounded_summary = next(f for e, f in bounded_logs if e == "activity_snapshots_synced")
    assert sequential_summary["concurrency"] == 1
    assert bounded_summary["concurrency"] == 4
    # Recorded before/after comparison (also visible in pytest -s output).
    print(
        "snapshot fixture 9 courses/111 activities: "
        f"sequential={sequential_seconds * 1000:.0f}ms "
        f"bounded4={bounded_seconds * 1000:.0f}ms "
        f"speedup={sequential_seconds / bounded_seconds:.2f}x"
    )
    # 111 x 20ms sequential is ~2.2s; the bounded pool must stay well under half.
    assert bounded_seconds < sequential_seconds / 2
    assert bounded_seconds < latency * 111 / 4 * 3  # generous CI headroom
