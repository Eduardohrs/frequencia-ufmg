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
