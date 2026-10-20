import queue
from collections.abc import MutableMapping
from typing import Any

from dms.acquisition.meters.dgtp import encode_dgtp_frame, parse_dgtp_frame
from dms.acquisition.meters.handler import MeterFrameHandler
from dms.acquisition.meters.parsing import OutOfRange
from dms.acquisition.serial.adapter import FrameOutcome
from dms.logs import events
from dms.messages import EngineMessage, MeterReading

OVERLOAD = b"OL,        ,kg"
UNDERLOAD = b"UL,        ,kg"
WEIGHT = encode_dgtp_frame(40).removesuffix(b"\r\n")


def build() -> tuple[MeterFrameHandler, queue.Queue[EngineMessage]]:
    messages: queue.Queue[EngineMessage] = queue.Queue()
    handler = MeterFrameHandler(
        meter_id="m1", port_name="/dev/fake", parser=parse_dgtp_frame, out_queue=messages
    )
    return handler, messages


def test_weight_is_published_with_the_given_stamps() -> None:
    handler, messages = build()

    outcome = handler.handle(WEIGHT, 11, 22)

    assert outcome is FrameOutcome.ACCEPTED
    assert messages.get_nowait() == MeterReading(
        meter_id="m1", value_kg=40, wall_ns=11, mono_ns=22
    )


def test_unparsable_frame_is_rejected_and_not_published() -> None:
    handler, messages = build()

    assert handler.handle(b"junk", 0, 0) is FrameOutcome.REJECTED
    assert messages.empty()


def test_overload_is_accepted_without_a_reading() -> None:
    handler, messages = build()

    assert handler.handle(OVERLOAD, 0, 0) is FrameOutcome.ACCEPTED
    assert messages.empty()


def test_out_of_range_is_logged_on_change_and_end(logs: list[MutableMapping[str, Any]]) -> None:
    handler, _ = build()

    for frame in [OVERLOAD, OVERLOAD, UNDERLOAD, WEIGHT]:
        handler.handle(frame, 0, 0)

    assert [(entry["event"], entry["status"]) for entry in logs] == [
        (events.METER_OUT_OF_RANGE, OutOfRange.OVERLOAD.value),
        (events.METER_OUT_OF_RANGE, OutOfRange.UNDERLOAD.value),
        (events.METER_BACK_IN_RANGE, OutOfRange.UNDERLOAD.value),
    ]
    assert all(entry["device_id"] == "m1" for entry in logs)


def test_weights_alone_log_nothing(logs: list[MutableMapping[str, Any]]) -> None:
    handler, _ = build()

    handler.handle(WEIGHT, 0, 0)

    assert logs == []
