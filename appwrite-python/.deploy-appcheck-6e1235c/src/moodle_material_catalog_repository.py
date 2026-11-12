"""Persist a bounded Moodle material catalogue without storing file bytes."""

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from course_repository import validate_course_id
from course_service import InvalidCourse

MAX_CANDIDATES = 500
MAX_CATALOG_BYTES = 750_000
_COURSE_KEYS = {
    "course_id",
    "course_code",
    "term",
    "moodle_course_id",
    "status",
    "candidates",
}
_CANDIDATE_KEYS = {
    "source_id",
    "moodle_course_id",
    "kind",
    "title",
    "url",
    "relevance",
    "origin",
}
_STATUSES = {"found", "empty", "unmatched", "ambiguous"}


class InvalidMoodleMaterialCatalog(Exception):
    """The material catalogue does not satisfy its persisted contract."""


class _Firestore(Protocol):
    def list_user_documents(self, *segments: str) -> list[dict[str, Any]]: ...

    def patch_user_document(
        self, *segments: str, fields: Mapping[str, Any]
    ) -> dict[str, Any]: ...


class MoodleMaterialCatalogRepository:
    def __init__(
        self,
        firestore: _Firestore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._firestore = firestore
        self._now = now or (lambda: datetime.now(UTC))

    def reconcile(self, courses: list[dict[str, object]]) -> dict[str, int]:
        if len(courses) > 50:
            raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
        validated = [_validate_course(course) for course in courses]
        if len({course["course_id"] for course in validated}) != len(validated):
            raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
        if sum(len(course["candidates"]) for course in validated) > MAX_CANDIDATES:
            raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")

        totals = {"created": 0, "updated": 0, "unchanged": 0, "removed": 0, "writes": 0}
        now = _timestamp(self._now())
        for course in validated:
            existing = self._load(course["course_id"])
            previous_candidates = (
                {candidate["source_id"]: candidate for candidate in existing["candidates"]}
                if existing is not None
                else {}
            )
            current_candidates = {
                candidate["source_id"]: candidate for candidate in course["candidates"]
            }
            totals["created"] += len(current_candidates.keys() - previous_candidates.keys())
            totals["removed"] += len(previous_candidates.keys() - current_candidates.keys())
            for source_id in current_candidates.keys() & previous_candidates.keys():
                field = (
                    "unchanged"
                    if current_candidates[source_id] == previous_candidates[source_id]
                    else "updated"
                )
                totals[field] += 1

            comparable = {
                "term": course["term"],
                "status": course["status"],
                "moodle_course_id": course["moodle_course_id"],
                "candidates": course["candidates"],
            }
            if existing is not None and all(
                existing[key] == value for key, value in comparable.items()
            ):
                continue
            created_at = existing["created_at"] if existing is not None else now
            self._firestore.patch_user_document(
                "courses",
                course["course_id"],
                "materialCatalog",
                "current",
                fields=_encode({**comparable, "created_at": created_at, "updated_at": now}),
            )
            totals["writes"] += 1
        return totals

    def list_catalog(self, courses: list[dict[str, Any]]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for course in courses:
            try:
                course_id = validate_course_id(course["id"])
                code = course["code"]
                term = course["term"]
            except (InvalidCourse, KeyError, TypeError):
                raise InvalidMoodleMaterialCatalog(
                    "invalid Moodle material catalogue"
                ) from None
            if (
                not isinstance(code, str)
                or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", code) is None
                or not isinstance(term, str)
                or re.fullmatch(r"20[2-9][0-9]-[12]", term) is None
            ):
                raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
            catalog = self._load(course_id)
            if catalog is None:
                continue
            if catalog["term"] != term:
                raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
            result.append(
                {
                    "course_id": course_id,
                    "course_code": code,
                    "term": term,
                    "moodle_course_id": catalog["moodle_course_id"],
                    "status": catalog["status"],
                    "candidates": catalog["candidates"],
                }
            )
        return sorted(result, key=lambda item: (str(item["course_code"]), str(item["course_id"])))

    def _load(self, course_id: str) -> dict[str, Any] | None:
        documents = self._firestore.list_user_documents(
            "courses", validate_course_id(course_id), "materialCatalog"
        )
        if not documents:
            return None
        if len(documents) != 1 or _document_id(documents[0]) != "current":
            raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
        return _decode(documents[0])


def _validate_course(value: Mapping[str, object]) -> dict[str, Any]:
    if set(value) != _COURSE_KEYS:
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    try:
        course_id = validate_course_id(value["course_id"])
    except InvalidCourse:
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue") from None
    code = value["course_code"]
    term = value["term"]
    status = value["status"]
    moodle_course_id = _nullable_moodle_id(value["moodle_course_id"])
    candidates = value["candidates"]
    if (
        not isinstance(code, str)
        or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", code) is None
        or not isinstance(term, str)
        or re.fullmatch(r"20[2-9][0-9]-[12]", term) is None
        or status not in _STATUSES
        or not isinstance(candidates, list)
        or len(candidates) > MAX_CANDIDATES
        or (status in {"found", "empty"}) != (moodle_course_id is not None)
        or (status == "found") != bool(candidates)
    ):
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    valid_candidates = [_validate_candidate(candidate, term) for candidate in candidates]
    if len({candidate["source_id"] for candidate in valid_candidates}) != len(
        valid_candidates
    ):
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    return {
        "course_id": course_id,
        "course_code": code,
        "term": term,
        "moodle_course_id": moodle_course_id,
        "status": status,
        "candidates": sorted(
            valid_candidates,
            key=lambda candidate: (int(candidate["source_id"]), candidate["title"]),
        ),
    }


def _validate_candidate(value: object, term: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _CANDIDATE_KEYS:
        raise InvalidMoodleMaterialCatalog("invalid Moodle material")
    source_id = _moodle_id(value["source_id"])
    moodle_course_id = _moodle_id(value["moodle_course_id"])
    kind = value["kind"]
    title = value["title"]
    url = value["url"]
    relevance = value["relevance"]
    origin = value["origin"]
    if (
        kind not in {"page", "file", "text"}
        or not isinstance(title, str)
        or not title
        or title.strip() != title
        or len(title) > 1_024
        or relevance not in {"teaching_plan", "schedule", "other"}
        or origin not in {"canonical", "metaturma"}
        or (kind == "text") != (url is None)
        or (url is not None and not _safe_material_url(url, term, source_id, str(kind)))
    ):
        raise InvalidMoodleMaterialCatalog("invalid Moodle material")
    return {
        "source_id": source_id,
        "moodle_course_id": moodle_course_id,
        "kind": kind,
        "title": title,
        "url": url,
        "relevance": relevance,
        "origin": origin,
    }


def _safe_material_url(value: object, term: str, source_id: str, kind: str) -> bool:
    if not isinstance(value, str) or len(value) > 4_096:
        return False
    parsed = urlsplit(value)
    expected_modules = {"page", "book"} if kind == "page" else {"resource", "folder"}
    query = parse_qs(parsed.query, keep_blank_values=True)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "virtual.ufmg.br"
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
        and parsed.path
        in {
            f"/{term.replace('-', '')}/mod/{module}/view.php"
            for module in expected_modules
        }
        and query == {"id": [source_id]}
    )


def _encode(value: Mapping[str, Any]) -> dict[str, Any]:
    materials_json = json.dumps(
        value["candidates"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(materials_json.encode()) > MAX_CATALOG_BYTES:
        raise InvalidMoodleMaterialCatalog("Moodle material catalogue is too large")
    digest = hashlib.sha256(materials_json.encode()).hexdigest()
    return {
        "schemaVersion": {"integerValue": "1"},
        "term": {"stringValue": value["term"]},
        "status": {"stringValue": value["status"]},
        "moodleCourseId": (
            {"stringValue": value["moodle_course_id"]}
            if value["moodle_course_id"] is not None
            else {"nullValue": None}
        ),
        "candidateCount": {"integerValue": str(len(value["candidates"]))},
        "metaturmaCandidateCount": {
            "integerValue": str(
                sum(candidate["origin"] == "metaturma" for candidate in value["candidates"])
            )
        },
        "materialsJson": {"stringValue": materials_json},
        "contentHash": {"stringValue": digest},
        "createdAt": {"timestampValue": value["created_at"]},
        "updatedAt": {"timestampValue": value["updated_at"]},
    }


def _decode(document: Mapping[str, Any]) -> dict[str, Any]:
    try:
        fields = document["fields"]
        if not isinstance(fields, Mapping) or set(fields) != {
            "schemaVersion",
            "term",
            "status",
            "moodleCourseId",
            "candidateCount",
            "metaturmaCandidateCount",
            "materialsJson",
            "contentHash",
            "createdAt",
            "updatedAt",
        }:
            raise KeyError
        if fields["schemaVersion"] != {"integerValue": "1"}:
            raise KeyError
        status = fields["status"]["stringValue"]
        term = fields["term"]["stringValue"]
        raw_moodle_id = fields["moodleCourseId"]
        moodle_course_id = (
            None if raw_moodle_id == {"nullValue": None} else raw_moodle_id["stringValue"]
        )
        materials_json = fields["materialsJson"]["stringValue"]
        content_hash = fields["contentHash"]["stringValue"]
        created_at = fields["createdAt"]["timestampValue"]
        updated_at = fields["updatedAt"]["timestampValue"]
        candidate_count = int(fields["candidateCount"]["integerValue"])
        metaturma_count = int(fields["metaturmaCandidateCount"]["integerValue"])
        if (
            not isinstance(materials_json, str)
            or len(materials_json.encode()) > MAX_CATALOG_BYTES
            or not isinstance(content_hash, str)
            or hashlib.sha256(materials_json.encode()).hexdigest() != content_hash
        ):
            raise KeyError
        raw_candidates = json.loads(materials_json)
        if not isinstance(raw_candidates, list):
            raise KeyError
        course = _validate_course(
            {
                "course_id": "validated-course",
                "course_code": "VALID",
                "term": term,
                "moodle_course_id": moodle_course_id,
                "status": status,
                "candidates": raw_candidates,
            }
        )
        candidates = course["candidates"]
        if (
            candidate_count != len(candidates)
            or metaturma_count
            != sum(candidate["origin"] == "metaturma" for candidate in candidates)
            or _timestamp(_instant(created_at)) != created_at
            or _timestamp(_instant(updated_at)) != updated_at
            or _instant(updated_at) < _instant(created_at)
        ):
            raise KeyError
        return {
            "status": status,
            "term": term,
            "moodle_course_id": moodle_course_id,
            "candidates": candidates,
            "created_at": created_at,
            "updated_at": updated_at,
        }
    except (
        InvalidMoodleMaterialCatalog,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue") from None


def _moodle_id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]{0,9}", value) is None:
        raise InvalidMoodleMaterialCatalog("invalid Moodle identifier")
    if int(value) > 2_147_483_647:
        raise InvalidMoodleMaterialCatalog("invalid Moodle identifier")
    return value


def _nullable_moodle_id(value: object) -> str | None:
    return None if value is None else _moodle_id(value)


def _document_id(document: Mapping[str, Any]) -> str:
    name = document.get("name")
    if not isinstance(name, str):
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    return name.rsplit("/", 1)[-1]


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidMoodleMaterialCatalog("invalid Moodle material catalogue")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
