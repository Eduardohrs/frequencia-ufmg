"""Discover Moodle resources and link them to local disciplines without persisting content."""

import re
from collections import defaultdict
from typing import Any, Protocol

from ufmg_session_store import UFMGReauthenticationRequired, UFMGSession


class _Sessions(Protocol):
    def load(self, user_id: str, *, now: int) -> UFMGSession | None: ...

    def delete(self, user_id: str) -> None: ...


class _Client(Protocol):
    def discover(
        self, token: str, *, term: str, course_codes: list[str]
    ) -> list[dict[str, object]]: ...


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class MoodleContentDiscoveryService:
    def __init__(self, sessions: _Sessions, client: _Client, courses: _Courses) -> None:
        self._sessions = sessions
        self._client = client
        self._courses = courses

    def discover(self, user_id: str, *, now: int) -> dict[str, object]:
        session = self._sessions.load(user_id, now=now)
        if session is None:
            raise UFMGReauthenticationRequired("UFMG reauthentication required")
        local_courses = self._courses.list_courses()
        by_term: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_code: dict[str, dict[str, Any]] = {}
        for course in local_courses:
            course_id = course.get("id")
            code = course.get("code")
            term = course.get("term")
            if (
                not isinstance(course_id, str)
                or not course_id
                or not isinstance(code, str)
                or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", code) is None
                or code in by_code
                or not isinstance(term, str)
                or re.fullmatch(r"20[2-9][0-9]-[12]", term) is None
            ):
                raise ValueError("invalid local course")
            by_code[code] = course
            by_term[term].append(course)
        if not by_term or len(by_term) > 2:
            raise ValueError("invalid local course terms")

        discovered: list[dict[str, object]] = []
        try:
            for term in sorted(by_term):
                codes = sorted(str(course["code"]) for course in by_term[term])
                for result in self._client.discover(session.token, term=term, course_codes=codes):
                    code = result.get("course_code")
                    matched_course = by_code.get(code) if isinstance(code, str) else None
                    if matched_course is None:
                        raise ValueError("unknown discovered course")
                    discovered.append(
                        {
                            "course_id": matched_course["id"],
                            "course_code": code,
                            "term": matched_course["term"],
                            "moodle_course_id": result["moodle_course_id"],
                            "status": result["status"],
                            "candidates": result["candidates"],
                        }
                    )
        except UFMGReauthenticationRequired:
            self._sessions.delete(user_id)
            raise

        courses = sorted(discovered, key=lambda item: str(item["course_code"]))
        counts = {status: 0 for status in ("found", "empty", "unmatched", "ambiguous")}
        candidate_total = 0
        metaturma_candidate_total = 0
        for course in courses:
            status = course["status"]
            candidates = course["candidates"]
            moodle_course_id = course["moodle_course_id"]
            has_moodle_course = (
                isinstance(moodle_course_id, str)
                and re.fullmatch(r"[1-9][0-9]{0,9}", moodle_course_id) is not None
                and int(moodle_course_id) <= 2_147_483_647
            )
            if (
                status not in counts
                or not isinstance(candidates, list)
                or (status in {"found", "empty"}) != has_moodle_course
                or (status in {"unmatched", "ambiguous"} and moodle_course_id is not None)
            ):
                raise ValueError("invalid discovery result")
            counts[str(status)] += 1
            candidate_total += len(candidates)
            metaturma_candidate_total += sum(
                isinstance(candidate, dict) and candidate.get("origin") == "metaturma"
                for candidate in candidates
            )
        if len(courses) != len(local_courses) or candidate_total > 500:
            raise ValueError("invalid discovery result")
        return {
            "courses": courses,
            "course_total": len(courses),
            "candidate_total": candidate_total,
            "metaturma_candidate_total": metaturma_candidate_total,
            **counts,
        }
