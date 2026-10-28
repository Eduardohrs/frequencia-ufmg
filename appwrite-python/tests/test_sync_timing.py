from sync_timing import timed_stage


def test_timing_delivery_failure_never_blocks_the_product_operation() -> None:
    def unavailable_telemetry(_event: str, _fields: object) -> None:
        raise RuntimeError("log sink unavailable")

    assert (
        timed_stage(
            "example",
            lambda: "result",
            telemetry=unavailable_telemetry,
            clock=iter([1.0, 1.1]).__next__,
        )
        == "result"
    )


def test_moodle_timing_preserves_exact_parser_reason_and_source_context():
    import pytest

    from moodle_structured_dates import InvalidMoodleResponse

    events = []

    def fail():
        raise InvalidMoodleResponse("activity_page_shape")

    with pytest.raises(InvalidMoodleResponse):
        timed_stage(
            "activity_snapshot_capture",
            fail,
            telemetry=lambda event, fields: events.append((event, fields)),
            clock=iter([1.0, 1.25]).__next__,
            fields={"source_id": "45758", "kind": "quiz", "course_code": "UNI001"},
        )
    assert events == [
        (
            "academic_sync_stage_failed",
            {
                "stage": "activity_snapshot_capture",
                "duration_ms": 250,
                "exception_type": "InvalidMoodleResponse",
                "reason": "activity_page_shape",
                "source_id": "45758",
                "kind": "quiz",
                "course_code": "UNI001",
            },
        )
    ]
