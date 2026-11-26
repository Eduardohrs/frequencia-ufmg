"""Per-sync discovery sharing, bounded page memoization and batched persistence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

import main as function
import moodle_structured_dates as msd
from activity_snapshot_repository import ActivitySnapshotMissing
from course_activities import CourseActivityService, _metric_map
from course_sync_policy import CourseSyncPolicy
from firestore_rest import FirestoreNotFound
from moodle_structured_dates import (
    InvalidMoodleResponse,
    MoodleStructuredDatesClient,
    _parse_course_states_full,
    _token_digest,
)

_ENROLLED = [
    {"id": 3701, "shortname": "DCC203 - POO", "fullname": "Programacao Orientada a Objetos"},
    {"id": 4953, "shortname": "MAT001", "fullname": "Calculo"},
]

_DCC203_CMS = [
    {
        "id": 101,
        "name": "Plano de ensino",
        "module": "page",
        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
        "uservisible": True,
    },
    {
        "id": 104,
        "name": "Trabalho 1",
        "module": "assign",
        "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=104",
        "uservisible": True,
    },
]


class _DiscoveryClient(MoodleStructuredDatesClient):
    """Client with a scripted AJAX layer that records every Moodle call."""

    def __init__(self, events, states_by_course=None):
        super().__init__(telemetry=lambda event, fields: events.append((event, dict(fields))))
        self.enrolled_calls = 0
        self.ajax_calls = []
        self._states_by_course = states_by_course or {3701: _DCC203_CMS, 4953: []}

    def _connect(self, token, term):
        return "/20262", "/20262/lib/ajax/service.php", "session-key"

    def _ajax(self, root, path, sesskey, calls):
        methods = [call["methodname"] for call in calls]
        self.ajax_calls.append(methods)
        payload = []
        for call in calls:
            method = call["methodname"]
            if method == "core_course_get_enrolled_courses_by_timeline_classification":
                self.enrolled_calls += 1
                payload.append(
                    {"error": False, "data": {"courses": _ENROLLED, "nextoffset": 2}}
                )
            elif method == "core_courseformat_get_state":
                course_id = call["args"]["courseid"]
                cms = self._states_by_course.get(course_id, [])
                payload.append(
                    {"error": False, "data": json.dumps({"course": {}, "section": [], "cm": cms})}
                )
            else:
                raise AssertionError(f"unexpected Moodle call: {method}")
        return json.dumps(payload).encode()


def test_discovery_shares_one_enrolled_and_one_state_batch_across_consumers():
    events = []
    client = _DiscoveryClient(events)

    materials = client.discover("token-a", term="2026-2", course_codes=["DCC203", "MAT001"])
    activities = client.discover("token-a", term="2026-2", course_codes=["DCC203"], activities=True)
    indexed = client.list_activities("token-a", term="2026-2", course_id=3701)
    via_code = client.list_activities(
        "token-a", term="2026-2", course_id=4953, course_code="MAT001"
    )

    assert client.enrolled_calls == 1
    assert client.ajax_calls == [
        ["core_course_get_enrolled_courses_by_timeline_classification"],
        ["core_courseformat_get_state", "core_courseformat_get_state"],
    ]
    assert [c["kind"] for c in materials[0]["candidates"]] == ["page"]
    assert [c["kind"] for c in activities[0]["candidates"]] == ["assign"]
    assert [entry["source_id"] for entry in indexed] == ["104"]
    assert via_code == []
    cache_events = [f for e, f in events if e == "moodle_discovery_cache"]
    assert [
        (f["consumer"], f["enrolled_hit"], f["state_hits"], f["state_misses"]) for f in cache_events
    ] == [
        ("material_catalog", False, 0, 2),
        ("activity_index", True, 1, 0),
        ("activity_snapshot_index", False, 1, 0),
        ("activity_index", True, 1, 0),
    ]


def test_combined_discovery_exposes_material_and_activity_views_from_same_states():
    client = _DiscoveryClient([])

    result = client.discover_with_activities(
        "token-a", term="2026-2", course_codes=["DCC203", "MAT001"]
    )

    assert [item["kind"] for item in result[0]["candidates"]] == ["page"]
    assert [item["kind"] for item in result[0]["activity_candidates"]] == ["assign"]
    assert result[1]["activity_candidates"] == []
    assert client.enrolled_calls == 1
    assert client.ajax_calls == [
        ["core_course_get_enrolled_courses_by_timeline_classification"],
        ["core_courseformat_get_state", "core_courseformat_get_state"],
    ]


def test_combined_discovery_limits_the_shared_activity_index(monkeypatch):
    monkeypatch.setattr(msd, "MAX_CANDIDATES", 1)
    states = {
        3701: [
            _DCC203_CMS[0],
            _DCC203_CMS[1],
            {
                **_DCC203_CMS[1],
                "id": 105,
                "name": "Trabalho 2",
                "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=105",
            },
        ],
        4953: [],
    }
    client = _DiscoveryClient([], states_by_course=states)

    with pytest.raises(InvalidMoodleResponse) as error:
        client.discover_with_activities(
            "token-a", term="2026-2", course_codes=["DCC203", "MAT001"]
        )
    assert error.value.reason == "activity_candidate_limit"


def test_combined_discovery_limits_activities_per_course(monkeypatch):
    monkeypatch.setattr(msd, "MAX_CANDIDATES", 2)
    states = {
        3701: [
            _DCC203_CMS[0],
            _DCC203_CMS[1],
            {
                **_DCC203_CMS[1],
                "id": 105,
                "name": "Trabalho 2",
                "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=105",
            },
        ],
        4953: [
            {
                **_DCC203_CMS[1],
                "id": 201,
                "name": "Lista 1",
                "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=201",
            },
            {
                **_DCC203_CMS[1],
                "id": 202,
                "name": "Lista 2",
                "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=202",
            },
        ],
    }
    client = _DiscoveryClient([], states_by_course=states)

    result = client.discover_with_activities(
        "token-a", term="2026-2", course_codes=["DCC203", "MAT001"]
    )

    assert [len(item["activity_candidates"]) for item in result] == [2, 2]


def test_discovery_cache_keys_are_scoped_to_token_and_term():
    client = _DiscoveryClient([])
    client.discover("token-a", term="2026-2", course_codes=["DCC203"])
    client.discover("token-a", term="2027-1", course_codes=["DCC203"])
    client.discover("token-b", term="2026-2", course_codes=["DCC203"])
    assert client.enrolled_calls == 3
    assert sorted(key[1] for key in client._enrolled_cache) == ["2026-2", "2026-2", "2027-1"]
    assert {key[0] for key in client._enrolled_cache} == {
        _token_digest("token-a"),
        _token_digest("token-b"),
    }


def test_discovery_cache_cap_of_zero_disables_memoization(monkeypatch):
    monkeypatch.setattr(msd, "MAX_DISCOVERY_CACHE_ENTRIES", 0)
    client = _DiscoveryClient([])
    client.discover("token-a", term="2026-2", course_codes=["DCC203"])
    client.discover("token-a", term="2026-2", course_codes=["DCC203"], activities=True)
    assert client.enrolled_calls == 2
    assert client.ajax_calls.count(["core_courseformat_get_state"]) == 2
    assert not client._enrolled_cache
    assert not client._state_cache


def test_token_change_drops_per_sync_discovery_memos():
    from test_moodle_structured_dates import (
        _course_list_response,
        _course_state_response,
        _dashboard,
        _Opener,
        _Response,
        _saml_page,
    )

    responses = []
    for _ in range(2):
        responses += [
            _Response(_saml_page(), "https://sistemas.ufmg.br/idp/profile/SAML2/Redirect/SSO"),
            _Response(_dashboard(), "https://virtual.ufmg.br/20262/my/"),
            _Response(
                _course_list_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
            _Response(
                _course_state_response(),
                "https://virtual.ufmg.br/20262/lib/ajax/service.php",
                content_type="application/json",
            ),
        ]
    opener = _Opener(responses)
    client = MoodleStructuredDatesClient(opener=opener)
    codes = ["DCC203", "MAT001"]
    client.discover("token-a", term="2026-2", course_codes=codes)
    assert len(client._enrolled_cache) == 1
    assert len(client._state_cache) == 2
    client.discover("token-b", term="2026-2", course_codes=codes)
    assert next(iter(client._enrolled_cache)) == (_token_digest("token-b"), "2026-2")
    assert len(client._state_cache) == 2
    enrolled = [
        request
        for request, _timeout in opener.requests
        if request.data
        and b"core_course_get_enrolled_courses_by_timeline_classification" in request.data
    ]
    assert len(enrolled) == 2


_ACTIVITY_PAGE = b'<main id="region-main"><div id="intro">Task</div></main>'


class _ActivityPageClient(MoodleStructuredDatesClient):
    def __init__(self, events):
        super().__init__(telemetry=lambda event, fields: events.append((event, dict(fields))))
        self.opens = 0

    def _connect(self, token, term):
        return "/20262", "/20262/lib/ajax/service.php", "session-key"

    def _open(self, request):
        self.opens += 1
        return _ACTIVITY_PAGE, request.full_url, "text/html"


def _cache_outcomes(events):
    return [f["outcome"] for e, f in events if e == "moodle_activity_page_cache"]


def test_fetch_activity_memoizes_one_page_per_activity_and_returns_copies():
    events = []
    client = _ActivityPageClient(events)
    first = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")
    second = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")
    assert client.opens == 1
    assert first == second
    first["description"] = "mutated"
    again = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")
    assert again["description"] == "Task"
    client.fetch_activity("token-a", term="2026-2", source_id=21, kind="assign")
    client.fetch_activity("token-b", term="2026-2", source_id=20, kind="assign")
    client.fetch_activity("token-a", term="2027-1", source_id=20, kind="assign")
    assert client.opens == 4
    assert _cache_outcomes(events) == ["miss", "hit", "hit", "miss", "miss", "miss"]


def test_fetch_activity_records_html_field_quality_without_changing_parser_contract():
    events = []
    client = _ActivityPageClient(events)
    detail = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")

    assert detail["description"] == "Task"
    assert detail["attachments"] == []
    assert detail["_html_response_status"] == 200
    assert detail["_html_response_bytes"] == len(_ACTIVITY_PAGE)
    assert detail["_html_description_chars"] == 4
    assert detail["_html_attachment_count"] == 0
    assert detail["_html_empty_fields"] == ["attachments"]


def test_fetch_activity_records_both_empty_optional_fields_as_valid_html():
    events = []
    client = _ActivityPageClient(events)
    empty_page = b'<section id="region-main"><div class="quizinfo">Quiz</div></section>'
    client._open = lambda request: (
        empty_page,
        request.full_url,
        "text/html",
    )

    detail = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="quiz")

    assert detail["description"] == ""
    assert detail["attachments"] == []
    assert detail["_html_description_chars"] == 0
    assert detail["_html_attachment_count"] == 0
    assert detail["_html_empty_fields"] == ["description", "attachments"]


def test_fetch_activity_records_nonempty_attachment_quality(monkeypatch):
    events = []
    client = _ActivityPageClient(events)
    monkeypatch.setattr(
        msd,
        "parse_activity_page",
        lambda payload, *, term, kind: {
            "description": "Instructions",
            "dates_text": "",
            "has_due_date": False,
            "submission_state": "unknown",
            "submission_text": "",
            "attachments": [{"name": "file.pdf", "url": "https://moodle/file"}],
        },
    )

    detail = client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")

    assert detail["_html_description_chars"] == len("Instructions")
    assert detail["_html_attachment_count"] == 1
    assert detail["_html_empty_fields"] == []


def test_fetch_activity_page_cache_cap_bounds_the_memo(monkeypatch):
    monkeypatch.setattr(msd, "MAX_ACTIVITY_PAGE_CACHE", 0)
    events = []
    client = _ActivityPageClient(events)
    client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")
    client.fetch_activity("token-a", term="2026-2", source_id=20, kind="assign")
    assert client.opens == 2
    assert not client._activity_page_cache
    assert _cache_outcomes(events) == ["miss", "miss"]


def _cm(source_id, module, title, url=None, visible=True):
    return {"id": source_id, "name": title, "module": module, "url": url, "uservisible": visible}


def _state_payload(cms_by_call):
    return json.dumps(
        [{"error": False, "data": json.dumps({"cm": cms})} for cms in cms_by_call]
    ).encode()


def test_parse_course_states_full_builds_both_views_from_one_response():
    states = _parse_course_states_full(
        _state_payload(
            [
                [
                    _cm(101, "page", "Plano", "https://virtual.ufmg.br/20262/mod/page/view.php?id=101"),
                    _cm(
                        102,
                        "resource",
                        "Arquivo.pdf",
                        "https://virtual.ufmg.br/20262/mod/resource/view.php?id=102",
                    ),
                    _cm(
                        104,
                        "assign",
                        "Trabalho 1",
                        "https://virtual.ufmg.br/20262/mod/assign/view.php?id=104",
                    ),
                    _cm(105, "quiz", "Quiz 1", "https://virtual.ufmg.br/20262/mod/quiz/view.php?id=105"),
                    _cm(106, "assign", "Hidden", visible=False),
                    _cm(107, "forum", "Forum"),
                ]
            ]
        ),
        "/20262",
        1,
    )
    assert [c["kind"] for c in states[0]["materials"]] == ["page", "file"]
    assert [c["kind"] for c in states[0]["activities"]] == ["assign", "quiz"]
    quiz_url = "https://virtual.ufmg.br/20262/mod/quiz/view.php?id=105"
    assert states[0]["activities"][1]["url"] == quiz_url


def test_parse_course_states_full_dedupes_and_rejects_conflicting_modules():
    assign_url = "https://virtual.ufmg.br/20262/mod/assign/view.php?id=104"
    same = _cm(104, "assign", "Trabalho 1", assign_url)
    states = _parse_course_states_full(_state_payload([[same, dict(same)]]), "/20262", 1)
    assert len(states[0]["activities"]) == 1

    quiz_url = "https://virtual.ufmg.br/20262/mod/quiz/view.php?id=104"
    conflict = _cm(104, "quiz", "Trabalho 1", quiz_url)
    with pytest.raises(InvalidMoodleResponse) as captured:
        _parse_course_states_full(_state_payload([[same, conflict]]), "/20262", 1)
    assert captured.value.reason == "course_module_conflict"


class _Catalog:
    def __init__(self, entries):
        self.entries = entries
        self.calls = 0

    def list_catalog(self, _courses):
        self.calls += 1
        return self.entries


def _activity_service(logs, catalog):
    entry = {
        "source_id": "20",
        "title": "Task",
        "kind": "assign",
        "url": "https://virtual.ufmg.br/20262/mod/assign/view.php?id=20",
        "relevance": "other",
    }
    course = {"id": "poo", "code": "ELE631", "term": "2026-2"}
    sessions = SimpleNamespace(load=lambda *a, **k: SimpleNamespace(token="synthetic-session"))
    client = SimpleNamespace(
        list_activities=lambda *a, **k: [entry],
        fetch_activity=lambda *a, **k: {
            "description": "Read this",
            "submission_state": "not_submitted",
            "attachments": [],
        },
    )
    tokens = SimpleNamespace(
        load=lambda *a, **k: SimpleNamespace(term="2026-2", private_token="p" * 32)
    )
    return CourseActivityService(
        SimpleNamespace(get_course=lambda _: course, list_courses=lambda: [course]),
        catalog,
        sessions,
        client,
        tokens,
        telemetry=lambda event, fields: logs.append((event, fields)),
    )


def test_source_uses_shared_discovery_entry_and_counts_catalog_fallback():
    logs = []
    catalog = _Catalog([{"status": "found", "moodle_course_id": "1"}])
    service = _activity_service(logs, catalog)

    _, _, moodle_id = service._source(
        "user", "poo", now=123, discovered={"poo": {"status": "found", "moodle_course_id": "7"}}
    )
    assert moodle_id == 7
    assert catalog.calls == 0
    assert service._catalog_reads == 0

    _, _, moodle_id = service._source("user", "poo", now=123, discovered={"poo": "broken"})
    assert moodle_id == 1
    assert catalog.calls == 1
    assert service._catalog_reads == 1

    _, _, moodle_id = service._source(
        "user", "poo", now=123, discovered={"other": {"status": "found", "moodle_course_id": "9"}}
    )
    assert moodle_id == 1
    assert catalog.calls == 2
    assert service._catalog_reads == 2


def test_metric_map_ignores_non_dict_values_and_invalid_counts():
    assert _metric_map({}, "missing") == {}
    assert _metric_map({"k": 3}, "k") == {}
    mixed = {"a": 2, "b": -1, "c": "x", "d": 0.5, "e": 0}
    assert _metric_map({"k": mixed}, "k") == {"a": 2, "e": 0}


class _CommitStore:
    def __init__(self, *, fail_commit=False):
        self.docs = {}
        self.reads = 0
        self.patches = 0
        self.commits = []
        self.fail_commit = fail_commit

    def get_user_document(self, *path):
        self.reads += 1
        if path not in self.docs:
            raise FirestoreNotFound()
        return deepcopy(self.docs[path])

    def patch_user_document(self, *path, fields):
        self.docs[path] = {"fields": deepcopy(fields)}
        self.patches += 1
        return self.docs[path]

    def commit_user_documents(self, *, updates, deletes):
        if self.fail_commit:
            raise RuntimeError("commit rejected")
        self.commits.append((updates, deletes))
        for path, fields in updates:
            self.docs[path] = {"fields": deepcopy(fields)}


class _PlainStore:
    def __init__(self):
        self.docs = {}
        self.writes = 0

    def get_user_document(self, *path):
        if path not in self.docs:
            raise FirestoreNotFound()
        return deepcopy(self.docs[path])

    def patch_user_document(self, *path, fields):
        self.docs[path] = {"fields": deepcopy(fields)}
        self.writes += 1


class _Snapshots:
    def __init__(self):
        self.saved = {}
        self.loads = 0

    def load(self, key):
        self.loads += 1
        if key not in self.saved:
            raise ActivitySnapshotMissing()
        return self.saved[key]

    def save(self, key, value):
        self.saved[key] = value


def test_sync_snapshots_shares_discovery_snapshot_and_policy_reads_per_course():
    logs = []
    catalog = _Catalog([{"status": "found", "moodle_course_id": "1"}])
    service = _activity_service(logs, catalog)
    store = _CommitStore()
    service._policy = CourseSyncPolicy(store)
    snapshots = _Snapshots()
    discovered = [{"course_id": "poo", "status": "found", "moodle_course_id": "1"}]

    result = service.sync_snapshots("user", now=1000, snapshots=snapshots, discovered=discovered)

    assert result["updated"] == 1
    assert catalog.calls == 0
    assert service._catalog_reads == 0
    assert snapshots.loads == 1
    assert store.reads == 1
    assert len(store.commits) == 1
    assert store.patches == 0

    read_cache = next(f for e, f in logs if e == "sync_read_cache")
    assert read_cache == {
        "stage": "moodle_activity_snapshots",
        "snapshot_reads": 1,
        "policy_state_reads": 1,
        "catalog_reads": 0,
        "discovery_shared_courses": 1,
        "policy_write_batch": True,
        "snapshot_write_batch": True,
    }
    synced = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert synced["activity_entries_seen"] == 1
    assert synced["html_activities"] == 1
    assert synced["fallback_by_kind"] == {}
    assert synced["fallback_reasons"] == {}


def test_persist_success_writes_one_document():
    store = _CommitStore()
    policy = CourseSyncPolicy(store)
    policy.persist_success("course1", "activities", {"source_key": "2026-2"})
    assert store.patches == 1
    path = ("courses", "course1", "syncState", "activities")
    state = json.loads(store.docs[path]["fields"]["stateJson"]["stringValue"])
    assert state == {"source_key": "2026-2"}


def test_persist_success_batch_empty_and_invalid_items():
    store = _CommitStore()
    policy = CourseSyncPolicy(store)
    policy.persist_success_batch([])
    assert store.commits == [] and store.patches == 0
    with pytest.raises(ValueError):
        policy.persist_success_batch([("course1", "unknown", {})])


def test_persist_success_batch_commits_once_and_keeps_latest_state():
    store = _CommitStore()
    policy = CourseSyncPolicy(store)
    policy.persist_success_batch(
        [
            ("course1", "activities", {"v": 1}),
            ("course2", "plan", {"v": 2}),
            ("course1", "activities", {"v": 3}),
        ]
    )
    assert len(store.commits) == 1
    updates, deletes = store.commits[0]
    assert deletes == []
    assert [path for path, _fields in updates] == [
        ("courses", "course1", "syncState", "activities"),
        ("courses", "course2", "syncState", "plan"),
    ]
    assert json.loads(updates[0][1]["stateJson"]["stringValue"]) == {"v": 3}
    assert json.loads(updates[1][1]["stateJson"]["stringValue"]) == {"v": 2}
    assert store.patches == 0


def test_persist_success_batch_falls_back_on_commit_failure():
    events = []
    store = _CommitStore(fail_commit=True)
    policy = CourseSyncPolicy(store, telemetry=lambda event, fields: events.append((event, fields)))
    policy.persist_success_batch(
        [("course1", "activities", {"v": 1}), ("course2", "plan", {"v": 2})]
    )
    assert store.commits == []
    assert store.patches == 2
    failed = [f for e, f in events if e == "course_sync_policy_batch_failed"]
    assert failed == [{"reason": "RuntimeError", "update_count": 2}]


def test_persist_success_batch_uses_per_item_saves_without_commit_support():
    store = _PlainStore()
    policy = CourseSyncPolicy(store)
    policy.persist_success_batch([("course1", "plan", {"v": 1})])
    assert store.writes == 1
    path = ("courses", "course1", "syncState", "plan")
    assert json.loads(store.docs[path]["fields"]["stateJson"]["stringValue"]) == {"v": 1}


def test_run_reuses_already_loaded_state_instead_of_reading_again():
    store = _CommitStore()
    policy = CourseSyncPolicy(store)
    policy.run("course1", "activities", "2026-2", now=1000, fetch=lambda: {"activity_count": 5})
    assert store.reads == 1
    loaded = {"source_key": "2026-2", "result": {"activity_count": 5}, "next_due_at": 99999}
    result, reused = policy.run(
        "course1",
        "activities",
        "2026-2",
        now=1001,
        fetch=lambda: {"activity_count": 9},
        state=loaded,
    )
    assert reused is True
    assert result == {"activity_count": 5}
    assert store.reads == 1


def test_discovered_courses_accepts_only_well_formed_course_lists():
    assert function._discovered_courses(None) is None
    assert function._discovered_courses("content") is None
    assert function._discovered_courses({}) is None
    assert function._discovered_courses({"courses": "no"}) is None
    assert function._discovered_courses({"courses": ["no"]}) is None
    assert function._discovered_courses({"courses": [{"course_id": "poo"}, 42]}) is None
    courses = [{"course_id": "poo", "status": "found", "moodle_course_id": "1"}]
    assert function._discovered_courses({"courses": courses}) == courses
