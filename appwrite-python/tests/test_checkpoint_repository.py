from copy import deepcopy

import pytest
from test_checkpoint_service import NOW, payload
from test_course_repository import _course, _document
from test_session_repository import _fields

from firestore_rest import FirestoreConflict, FirestoreUnavailable
from session_repository import SessionMutationRepository


class Store:
    def __init__(self):
        self.course = _document(_course("poo"))
        self.session = {
            "name": "root/s",
            "fields": _fields(firstPing={"nullValue": None}),
            "updateTime": "2026-10-08T18:30:00Z",
        }
        self.writes = []
        self.conflict = False

    def get_user_document(self, *path):
        return deepcopy(self.course if len(path) == 2 else self.session)

    def patch_user_document(self, *path, fields, update_mask, expected_update_time):
        if self.conflict:
            raise FirestoreConflict("changed")
        assert expected_update_time == self.session["updateTime"]
        self.writes.append((path, fields, update_mask))
        self.session["fields"].update(fields)
        return self.session


def test_conditional_write_is_idempotent_and_keeps_calendar_and_schedule():
    store = Store()
    repo = SessionMutationRepository(store, now=lambda: NOW)
    original = deepcopy(store.session)
    result = repo.apply_checkpoints("poo", "s", payload())
    assert result["outcome"] == "applied" and result["absences"] == 1
    assert repo.apply_checkpoints("poo", "s", payload())["outcome"] == "already_applied"
    assert len(store.writes) == 1
    assert set(store.writes[0][1]) == {
        "firstPing",
        "secondPing",
        "attendanceStatus",
        "absences",
        "updatedAt",
    }
    for field in ("startsAt", "endsAt", "calendarStatus", "lessonCount", "callCount"):
        assert store.session["fields"][field] == original["fields"][field]


def test_manual_correction_after_apply_remains_authoritative_on_retry():
    store = Store()
    repo = SessionMutationRepository(store, now=lambda: NOW)
    repo.apply_checkpoints("poo", "s", payload())
    store.session["fields"].update(
        attendanceStatus={"stringValue": "presente"}, absences={"integerValue": "0"}
    )
    assert repo.apply_checkpoints("poo", "s", payload())["reason"] == "existing_attendance"
    assert len(store.writes) == 1


def test_concurrent_edit_and_missing_revision_fail_without_unconditional_write():
    store = Store()
    store.conflict = True
    with pytest.raises(FirestoreConflict):
        SessionMutationRepository(store, now=lambda: NOW).apply_checkpoints("poo", "s", payload())
    assert not store.writes
    del store.session["updateTime"]
    with pytest.raises(FirestoreUnavailable):
        SessionMutationRepository(store, now=lambda: NOW).apply_checkpoints("poo", "s", payload())


def test_online_course_is_preserved_without_writes():
    store = Store()
    store.course = _document(
        {**_course("poo"), "modality": "online", "attendance_policy": "no_call"}
    )
    result = SessionMutationRepository(store, now=lambda: NOW).apply_checkpoints(
        "poo", "s", payload()
    )
    assert result["reason"] == "course_without_roll_call" and not store.writes
