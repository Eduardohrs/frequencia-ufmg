"""Bounded concurrency for the Moodle activity snapshot stage."""

import copy
import threading
import time
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

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


def _build(courses, index, fetch, *, max_workers=DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY, logs=None):
    logs = [] if logs is None else logs
    client = _Client(index, fetch)
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
            load=lambda *args, **kwargs: SimpleNamespace(term="2026-2", private_token="p" * 32)
        ),
        telemetry=lambda event, fields: logs.append((event, dict(fields))),
        max_workers=max_workers,
    )
    return service, client, logs


def _bare_service(max_workers=None) -> CourseActivityService:
    kwargs = {} if max_workers is None else {"max_workers": max_workers}
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
    summary = next(fields for event, fields in logs if event == "activity_snapshots_synced")
    assert summary["total_courses"] == 1
    assert summary["updated"] == 1
    assert summary["failed"] == 0
    assert summary["failed_activities"] == 0
    assert summary["concurrency"] == 4
    assert isinstance(summary["duration_ms"], int)
    assert "reused" not in summary


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
    assert _bare_service()._max_workers == DEFAULT_ACTIVITY_SNAPSHOT_CONCURRENCY == 4


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
