"""Replay of the recorded 2026-11-25 Moodle sync run (operation sync-hoi5z6p8qg-7rtfsx).

The fixture reproduces the measured shape of that run: 10 enrolled courses in
one term, 115 indexed activity entries (11 quizzes in FIS086/UNI001 whose bulk
payload lacks description/attachments), 43 calendar events over 2 monthly
calls.  It asserts the Moodle call counts after the per-sync discovery cache and
that no user-visible data is lost.  Every number here is a replay count or a
fixture size, not wall time; the recorded wall time was 51,495 ms for the whole
operation and must be re-measured on a real run after deployment.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from test_moodle_date_import import _Client, _Dates, _event, _Sessions

from course_activities import CourseActivityService
from moodle_date_import import MoodleDateImportService
from moodle_structured_dates import MoodleStructuredDatesClient

TERM = "2026-2"
NOW = 1_800_000_000

# code -> moodle course id, matching the recorded run's 10-course term.
COURSE_CODES = [
    "FIS086",
    "UNI001",
    "DCC203",
    "DCC205",
    "MAT001",
    "QUI010",
    "LET020",
    "DIR030",
    "MED040",
    "ENG050",
]
COURSE_IDS = {code: 3701 + index for index, code in enumerate(COURSE_CODES)}
QUIZ_COURSES = {"FIS086": 6, "UNI001": 5}


def _activity_entries():
    """115 indexed entries: 104 assignments plus the 11 recorded quiz fallbacks."""

    entries_by_course = {}
    source_id = 1000
    for code in COURSE_CODES:
        entries = []
        quiz_count = QUIZ_COURSES.get(code, 0)
        total = 20 if code == "FIS086" else 15 if code == "UNI001" else 10
        for position in range(total):
            source_id += 1
            kind = "quiz" if position < quiz_count else "assign"
            entries.append(
                {
                    "source_id": str(source_id),
                    "kind": kind,
                    "title": f"{code} activity {position}",
                    "url": f"https://virtual.ufmg.br/20262/mod/{kind}/view.php?id={source_id}",
                    "relevance": "other",
                    "moodle_course_id": str(COURSE_IDS[code]),
                }
            )
        entries_by_course[code] = entries
    return entries_by_course


ENTRIES = _activity_entries()
ALL_ENTRIES = [entry for entries in ENTRIES.values() for entry in entries]
QUIZ_IDS = {int(entry["source_id"]) for entry in ALL_ENTRIES if entry["kind"] == "quiz"}


def _course_dicts():
    return [
        {"id": code.lower(), "code": code, "term": TERM} for code in COURSE_CODES
    ]


def _cms_for_course(code):
    cms = [
        {
            "id": 500 + COURSE_IDS[code],
            "name": f"{code} plano de ensino",
            "module": "page",
            "url": f"https://virtual.ufmg.br/20262/mod/page/view.php?id={500 + COURSE_IDS[code]}",
            "uservisible": True,
        }
    ]
    for entry in ENTRIES[code]:
        cms.append(
            {
                "id": int(entry["source_id"]),
                "name": entry["title"],
                "module": entry["kind"],
                "url": entry["url"],
                "uservisible": True,
            }
        )
    return cms


class _ReplayDiscoveryClient(MoodleStructuredDatesClient):
    """Scripted AJAX layer replaying the recorded term's enrolled/state calls."""

    def __init__(self, events):
        super().__init__(telemetry=lambda event, fields: events.append((event, dict(fields))))
        self.enrolled_calls = 0
        self.state_batches = []
        self.ajax_calls = []

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
                courses = [
                    {"id": COURSE_IDS[code], "shortname": code, "fullname": f"Disciplina {code}"}
                    for code in COURSE_CODES
                ]
                payload.append({"error": False, "data": {"courses": courses, "nextoffset": 10}})
            elif method == "core_courseformat_get_state":
                course_id = call["args"]["courseid"]
                self.state_batches.append(course_id)
                code = next(c for c in COURSE_CODES if COURSE_IDS[c] == course_id)
                data = {"course": {}, "section": [], "cm": _cms_for_course(code)}
                payload.append({"error": False, "data": json.dumps(data)})
            else:
                raise AssertionError(f"unexpected Moodle call: {method}")
        return json.dumps(payload).encode()


def test_replay_discovery_makes_one_enrolled_and_one_state_batch_for_ten_courses():
    """Recorded run: 10 enrolled calls + 10 state calls. Replay after the cache."""

    events = []
    client = _ReplayDiscoveryClient(events)

    # Same call sequence as one sync: material catalog per term, activity index
    # per course, then the snapshot stage's per-course index reads.
    client.discover("token", term=TERM, course_codes=COURSE_CODES)
    client.discover("token", term=TERM, course_codes=COURSE_CODES, activities=True)
    indexed = [
        client.list_activities("token", term=TERM, course_id=COURSE_IDS[code], course_code=code)
        for code in COURSE_CODES
    ]

    assert client.enrolled_calls == 1
    assert len(client.state_batches) == 10
    assert len(client.ajax_calls) == 2
    assert client.ajax_calls[0] == ["core_course_get_enrolled_courses_by_timeline_classification"]
    assert client.ajax_calls[1] == ["core_courseformat_get_state"] * 10
    assert sum(len(entries) for entries in indexed) == 115
    assert sum(1 for entries in indexed for entry in entries if entry["kind"] == "quiz") == 11
    hits = [f for e, f in events if e == "moodle_discovery_cache"]
    assert hits[0]["enrolled_hit"] is False and hits[0]["state_misses"] == 10
    assert all(f["enrolled_hit"] is True and f["state_misses"] == 0 for f in hits[1:])


class _ReplayActivityClient:
    """Activity client replaying the recorded bulk + 11 page fallbacks."""

    bulk_activity_details_complete = True

    def __init__(self):
        self.updates_calls = []
        self.bulk_calls = []
        self.pages = []

    def list_activities(self, token, *, term, course_id, course_code=None):
        code = next(c for c in COURSE_CODES if COURSE_IDS[c] == course_id)
        return ENTRIES[code]

    def activity_updates_since(self, token, *, term, course_id, since):
        self.updates_calls.append(course_id)
        code = next(c for c in COURSE_CODES if COURSE_IDS[c] == course_id)
        return {int(e["source_id"]) for e in ENTRIES[code] if int(e["source_id"]) in QUIZ_IDS}

    def fetch_course_activity_bulk(self, *, webservice_token, private_token, term, course_id):
        self.bulk_calls.append(course_id)
        code = next(c for c in COURSE_CODES if COURSE_IDS[c] == course_id)
        details = {}
        for entry in ENTRIES[code]:
            if int(entry["source_id"]) in QUIZ_IDS:
                # Recorded behavior: mod_quiz bulk entries omit description and
                # attachments, so the client keeps a bounded HTML fallback.
                details[entry["source_id"]] = {
                    "_bulk_description_present": False,
                    "_bulk_attachments_present": False,
                    "submission_state": "unknown",
                }
        return details

    def fetch_activity(self, token, *, term, source_id, kind):
        self.pages.append((source_id, kind))
        return {
            "description": f"Quiz {source_id} description",
            "dates_text": "",
            "has_due_date": True,
            "submission_state": "not_submitted",
            "submission_text": "",
            "attachments": [{"name": f"quiz-{source_id}.pdf", "url": "https://example.invalid/f"}],
        }


class _ReplaySnapshots:
    def __init__(self):
        self.saved = {}
        self.loads = 0
        epoch = datetime.fromtimestamp(NOW - 60, UTC).isoformat().replace("+00:00", "Z")
        for code in COURSE_CODES:
            self.saved[code.lower()] = {
                "course_id": code.lower(),
                "term": TERM,
                "synced_at": epoch,
                "activities": [
                    {
                        **entry,
                        "description": "cached",
                        "dates_text": "",
                        "has_due_date": True,
                        "submission_state": "submitted",
                        "submission_text": "",
                        "attachments": [],
                        "files": [],
                        "term": TERM,
                    }
                    for entry in ENTRIES[code]
                ],
            }

    def load(self, key):
        self.loads += 1
        from activity_snapshot_repository import ActivitySnapshotMissing

        if key not in self.saved:
            raise ActivitySnapshotMissing()
        return self.saved[key]

    def save(self, key, value):
        self.saved[key] = value


def test_replay_activity_stage_preserves_entries_and_bounds_the_quiz_fallback():
    """Recorded run: 115 entries, 104 reused details, 11 HTML pages (6 FIS086 + 5 UNI001)."""

    logs = []
    client = _ReplayActivityClient()
    courses = SimpleNamespace(
        get_course=lambda course_id: next(c for c in _course_dicts() if c["id"] == course_id),
        list_courses=lambda: _course_dicts(),
    )
    def _no_catalog_read(_courses):
        raise AssertionError("catalog read must not happen when discovery is shared")

    catalog = SimpleNamespace(list_catalog=_no_catalog_read)
    sessions = SimpleNamespace(load=lambda *a, **k: SimpleNamespace(token="synthetic-session"))
    tokens = SimpleNamespace(
        load=lambda *a, **k: SimpleNamespace(
            term=TERM, webservice_token="ws-token", private_token="p" * 32
        )
    )
    service = CourseActivityService(
        courses,
        catalog,
        sessions,
        client,
        tokens,
        telemetry=lambda event, fields: logs.append((event, dict(fields))),
    )
    snapshots = _ReplaySnapshots()
    discovered = [
        {"course_id": code.lower(), "status": "found", "moodle_course_id": str(COURSE_IDS[code])}
        for code in COURSE_CODES
    ]

    result = service.sync_snapshots("user", now=NOW, snapshots=snapshots, discovered=discovered)

    assert result["updated"] == 10
    assert result["failed"] == 0
    assert snapshots.loads == 10
    assert len(client.updates_calls) == 10
    assert sorted(client.bulk_calls) == sorted([COURSE_IDS["FIS086"], COURSE_IDS["UNI001"]])
    assert len(client.pages) == 11
    assert {kind for _sid, kind in client.pages} == {"quiz"}
    assert {sid for sid, _kind in client.pages} == QUIZ_IDS
    synced = next(f for e, f in logs if e == "activity_snapshots_synced")
    assert synced["activity_entries_seen"] == 115
    assert synced["reused_activities"] == 104
    assert synced["html_activities"] == 11
    assert synced["bulk_fallbacks"] == 11
    assert synced["updates_checked"] == 10
    assert synced["updates_changed"] == 11
    assert synced["fallback_by_kind"] == {"quiz": 11}
    assert synced["fallback_reasons"] == {"missing_bulk_fields": 11}
    read_cache = next(f for e, f in logs if e == "sync_read_cache")
    assert read_cache["catalog_reads"] == 0
    assert read_cache["discovery_shared_courses"] == 10
    assert read_cache["snapshot_reads"] == 10
    # Every saved snapshot keeps the fallback details (description + attachments).
    for code in COURSE_CODES:
        saved = snapshots.saved[code.lower()]
        quizzes = [a for a in saved["activities"] if a["kind"] == "quiz"]
        expected = QUIZ_COURSES.get(code, 0)
        assert len(quizzes) == expected
        for quiz in quizzes:
            assert quiz["description"] == f"Quiz {quiz['source_id']} description"
            assert quiz["attachments"]


class _TermCourses:
    def __init__(self, courses):
        self._courses = courses

    def list_courses(self):
        return self._courses


class _TermClient(_Client):
    def __init__(self, events_by_term):
        super().__init__([])
        self.events_by_term = events_by_term
        self.terms = []

    def fetch(self, token, *, term, months):
        self.terms.append(term)
        return self.events_by_term[term]


def _calendar_courses():
    courses = []
    for index, code in enumerate(COURSE_CODES[:5]):
        courses.append(
            {
                "id": f"t1-{index}",
                "code": code,
                "name": f"Disciplina {code}",
                "term": "2026-1",
                "starts_on": "2026-02-01T00:00:00Z",
                "ends_on": "2026-06-30T00:00:00Z",
            }
        )
    for index, code in enumerate(COURSE_CODES[5:]):
        courses.append(
            {
                "id": f"t2-{index}",
                "code": code,
                "name": f"Disciplina {code}",
                "term": "2026-2",
                "starts_on": "2026-07-01T00:00:00Z",
                "ends_on": "2026-12-31T00:00:00Z",
            }
        )
    return courses


def test_replay_calendar_keeps_all_43_events_across_the_two_term_fetches():
    """Recorded run: 2 monthly_view calls, 43 events matched and unchanged."""

    logs = []
    events_by_term = {}
    source_id = 9000
    kinds = ["assignment", "quiz", "event"]
    for term, codes in (("2026-1", COURSE_CODES[:5]), ("2026-2", COURSE_CODES[5:])):
        events = []
        count = 22 if term == "2026-1" else 21
        for position in range(count):
            source_id += 1
            events.append(
                _event(
                    source_id=str(source_id),
                    course_shortname=f"{codes[position % len(codes)]} - Turma",
                    kind=kinds[position % 3],
                )
            )
        events_by_term[term] = events
    client = _TermClient(events_by_term)
    service = MoodleDateImportService(
        _Sessions(),
        client,
        _TermCourses(_calendar_courses()),
        _Dates(),
        telemetry=lambda e, f: logs.append((e, dict(f))),
    )

    result = service.import_dates("user", now=123)

    assert client.terms == ["2026-1", "2026-2"]
    assert result["total"] == 43
    assert result["matched"] == 43
    assert result["unmatched"] == 0
    kinds_event = next(f for e, f in logs if e == "moodle_calendar_event_kinds")
    assert kinds_event["total"] == 43
    assert kinds_event["matched"] == 43
    assert kinds_event["unique_source_ids"] == 43
    assert sum(kinds_event["kinds"].values()) == 43
    assert kinds_event["kinds"] == {"assignment": 15, "quiz": 14, "event": 14}
