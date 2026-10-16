"""Expose the persisted Moodle material catalogue to authenticated clients."""

from typing import Any, Protocol


class _Courses(Protocol):
    def list_courses(self) -> list[dict[str, Any]]: ...


class _Catalog(Protocol):
    def list_catalog(self, courses: list[dict[str, Any]]) -> list[dict[str, object]]: ...


class MoodleMaterialCatalogService:
    def __init__(self, courses: _Courses, catalog: _Catalog) -> None:
        self._courses = courses
        self._catalog = catalog

    def list_catalog(self) -> dict[str, object]:
        courses = self._catalog.list_catalog(self._courses.list_courses())
        counts = {status: 0 for status in ("found", "empty", "unmatched", "ambiguous")}
        candidate_total = 0
        metaturma_total = 0
        for course in courses:
            status = str(course["status"])
            candidates = course["candidates"]
            if status not in counts or not isinstance(candidates, list):
                raise ValueError("invalid Moodle material catalogue")
            counts[status] += 1
            candidate_total += len(candidates)
            metaturma_total += sum(
                isinstance(candidate, dict) and candidate.get("origin") == "metaturma"
                for candidate in candidates
            )
        if len(courses) > 50 or candidate_total > 500:
            raise ValueError("invalid Moodle material catalogue")
        return {
            "courses": courses,
            "course_total": len(courses),
            "candidate_total": candidate_total,
            "metaturma_candidate_total": metaturma_total,
            **counts,
        }
