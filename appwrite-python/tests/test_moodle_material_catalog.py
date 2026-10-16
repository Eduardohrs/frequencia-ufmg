from typing import Any

import pytest

from moodle_material_catalog import MoodleMaterialCatalogService


class _Courses:
    def list_courses(self) -> list[dict[str, Any]]:
        return [
            {"id": "course-b", "code": "MAT001", "term": "2026-2"},
            {"id": "course-a", "code": "DCC203", "term": "2026-2"},
        ]


class _Catalog:
    def list_catalog(self, courses: list[dict[str, Any]]) -> list[dict[str, object]]:
        assert len(courses) == 2
        return [
            {
                "course_id": "course-a",
                "course_code": "DCC203",
                "term": "2026-2",
                "moodle_course_id": "3701",
                "status": "found",
                "candidates": [
                    {
                        "source_id": "101",
                        "moodle_course_id": "3701",
                        "kind": "page",
                        "title": "Plano",
                        "url": "https://virtual.ufmg.br/20262/mod/page/view.php?id=101",
                        "relevance": "teaching_plan",
                        "origin": "canonical",
                    },
                    {
                        "source_id": "102",
                        "moodle_course_id": "4999",
                        "kind": "file",
                        "title": "Lista",
                        "url": "https://virtual.ufmg.br/20262/mod/resource/view.php?id=102",
                        "relevance": "other",
                        "origin": "metaturma",
                    },
                ],
            },
            {
                "course_id": "course-b",
                "course_code": "MAT001",
                "term": "2026-2",
                "moodle_course_id": "4953",
                "status": "empty",
                "candidates": [],
            },
        ]


def test_lists_persisted_catalog_with_bounded_aggregate_counts() -> None:
    result = MoodleMaterialCatalogService(_Courses(), _Catalog()).list_catalog()

    assert result["course_total"] == 2
    assert result["candidate_total"] == 2
    assert result["metaturma_candidate_total"] == 1
    assert result["found"] == 1
    assert result["empty"] == 1
    assert result["unmatched"] == 0
    assert result["ambiguous"] == 0
    assert len(result["courses"]) == 2


@pytest.mark.parametrize(
    "courses",
    [
        [{"status": "invalid", "candidates": []}],
        [{"status": "found", "candidates": "invalid"}],
        [{"status": "empty", "candidates": []}] * 51,
        [{"status": "found", "candidates": [{}] * 501}],
    ],
)
def test_rejects_invalid_or_unbounded_repository_results(
    courses: list[dict[str, object]],
) -> None:
    class Catalog:
        def list_catalog(self, _courses: list[dict[str, Any]]) -> list[dict[str, object]]:
            return courses

    with pytest.raises(ValueError):
        MoodleMaterialCatalogService(_Courses(), Catalog()).list_catalog()
