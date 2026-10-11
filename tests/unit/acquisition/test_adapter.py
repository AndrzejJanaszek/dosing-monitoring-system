import queue
import threading
from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest
from structlog.testing import capture_logs

from dms.acquisition.meters.adapter import MeterAdapter, SerialPort
from dms.acquisition.meters.dgtp import encode_dgtp_frame, parse_dgtp_frame
from dms.acquisition.meters.framing import Framer
from dms.logs import events
from dms.messages import EngineMessage, MeterReading
from tests.fakes import ManualClock

RECONNECT_DELAY_S = 5.0
SILENCE_TIMEOUT_S = 3.0


class FakePort:
    def __init__(self, script: list[bytes | Exception]) -> None:
        self._script = script
        self.closed = False

    def read(self, size: int, /) -> bytes:
        if not self._script:
            return b""
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def feed(self, data: bytes) -> None:
        self._script.append(data)

    def close(self) -> None:
        self.closed = True


class ScriptedOpener:
    def __init__(self, outcomes: list[FakePort | Exception]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def __call__(self) -> SerialPort:
        self.calls += 1
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Harness:
    def __init__(self, outcomes: list[FakePort | Exception]) -> None:
        self.clock = ManualClock()
        self.messages: queue.Queue[EngineMessage] = queue.Queue()
        self.opener = ScriptedOpener(outcomes)
        self.adapter = MeterAdapter(
            meter_id="m1",
            port_name="/dev/fake",
            port_opener=self.opener,
            framer=Framer(b"", b"\r\n"),
            parser=parse_dgtp_frame,
            clock=self.clock,
            out_queue=self.messages,
            stop_event=threading.Event(),
            reconnect_delay_s=RECONNECT_DELAY_S,
            silence_timeout_s=SILENCE_TIMEOUT_S,
            wait=self.clock.waiter(),
        )

    def steps(self, count: int) -> None:
        for _ in range(count):
            self.adapter.step()

    def readings(self) -> list[MeterReading]:
        items: list[MeterReading] = []
        while not self.messages.empty():
            message = self.messages.get_nowait()
            assert isinstance(message, MeterReading)
            items.append(message)
        return items


def event_names(logs: list[MutableMapping[str, Any]]) -> list[object]:
    return [entry["event"] for entry in logs]


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured


def test_valid_frame_becomes_reading_with_clock_stamps(
    logs: list[MutableMapping[str, Any]],
) -> None:
    harness = Harness([FakePort([encode_dgtp_frame(1020)])])
    harness.clock.advance(7)

    harness.steps(2)

    (reading,) = harness.readings()
    assert reading == MeterReading("m1", 1020, harness.clock.wall_ns(), harness.clock.mono_ns())
    assert event_names(logs) == [events.PORT_OPENED]


def test_frames_split_across_reads_are_assembled() -> None:
    harness = Harness([FakePort([b"ST,    10", b"20,kg\r", b"\nST,    1040,kg\r\n"])])

    harness.steps(4)

    assert [reading.value_kg for reading in harness.readings()] == [1020, 1040]


def test_garbage_gives_no_reading_and_limited_log(logs: list[MutableMapping[str, Any]]) -> None:
    harness = Harness([FakePort([b"junk\r\n"] * 250)])

    harness.steps(251)

    assert harness.readings() == []
    garbage_warnings = [
        entry
        for entry in logs
        if entry["event"] == events.PORT_GARBAGE and "rejected_count" in entry
    ]
    assert [entry["rejected_count"] for entry in garbage_warnings] == [1, 100, 200]


def test_read_error_closes_port_and_reconnects_after_delay(
    logs: list[MutableMapping[str, Any]],
) -> None:
    first = FakePort([OSError("unplugged")])
    second = FakePort([encode_dgtp_frame(50)])
    harness = Harness([first, second])

    harness.steps(2)
    assert first.closed
    assert event_names(logs) == [events.PORT_OPENED, events.PORT_DISCONNECTED]

    harness.steps(2)
    assert harness.opener.calls == 1

    harness.clock.advance(RECONNECT_DELAY_S)
    harness.steps(2)
    assert harness.opener.calls == 2
    assert [reading.value_kg for reading in harness.readings()] == [50]


def test_partial_frame_is_dropped_on_reconnect() -> None:
    first = FakePort([b"ST,    1", OSError("unplugged")])
    second = FakePort([b"ST,      66,kg\r\n"])
    harness = Harness([first, second])

    harness.steps(3)
    harness.clock.advance(RECONNECT_DELAY_S)
    harness.steps(3)

    assert [reading.value_kg for reading in harness.readings()] == [66]


def test_missing_port_at_start_keeps_retrying_and_logs_once(
    logs: list[MutableMapping[str, Any]],
) -> None:
    harness = Harness([OSError("no such device")])

    harness.steps(3)
    for _ in range(3):
        harness.clock.advance(RECONNECT_DELAY_S)
        harness.steps(1)

    assert harness.opener.calls == 4
    assert event_names(logs) == [events.PORT_OPEN_FAILED]


def test_port_appearing_later_starts_delivering() -> None:
    harness = Harness([OSError("no such device"), FakePort([encode_dgtp_frame(30)])])

    harness.steps(1)
    harness.clock.advance(RECONNECT_DELAY_S)
    harness.steps(2)

    assert [reading.value_kg for reading in harness.readings()] == [30]


def test_silence_forces_reconnect_and_logs_end(logs: list[MutableMapping[str, Any]]) -> None:
    quiet = FakePort([])
    revived = FakePort([encode_dgtp_frame(77)])
    harness = Harness([quiet, revived])

    harness.steps(1)
    harness.clock.advance(SILENCE_TIMEOUT_S)
    harness.steps(1)
    assert quiet.closed

    harness.steps(2)
    assert [reading.value_kg for reading in harness.readings()] == [77]
    assert event_names(logs) == [
        events.PORT_OPENED,
        events.PORT_SILENCE,
        events.PORT_OPENED,
        events.PORT_SILENCE_ENDED,
    ]
    ended = logs[-1]
    assert ended["duration_s"] == SILENCE_TIMEOUT_S


def test_continuing_silence_is_logged_once(logs: list[MutableMapping[str, Any]]) -> None:
    harness = Harness([FakePort([]), FakePort([]), FakePort([])])

    for _ in range(3):
        harness.steps(1)
        harness.clock.advance(SILENCE_TIMEOUT_S)
        harness.steps(1)

    assert event_names(logs).count(events.PORT_SILENCE) == 1


def test_valid_frames_keep_the_port_open() -> None:
    port = FakePort([])
    harness = Harness([port])
    harness.steps(1)

    for _ in range(5):
        harness.clock.advance(SILENCE_TIMEOUT_S - 1)
        port._script.append(encode_dgtp_frame(10))
        harness.steps(1)

    assert not port.closed
    assert len(harness.readings()) == 5


def test_run_stops_and_closes_port_when_stop_event_is_set() -> None:
    port = FakePort([])
    clock = ManualClock()
    stop = threading.Event()
    adapter = MeterAdapter(
        meter_id="m1",
        port_name="/dev/fake",
        port_opener=ScriptedOpener([port]),
        framer=Framer(b"", b"\r\n"),
        parser=parse_dgtp_frame,
        clock=clock,
        out_queue=queue.Queue(),
        stop_event=stop,
        reconnect_delay_s=RECONNECT_DELAY_S,
        silence_timeout_s=SILENCE_TIMEOUT_S,
        wait=clock.waiter(),
    )
    stop.set()

    adapter.run()

    assert not port.closed

    stop.clear()
    adapter.step()
    stop.set()
    adapter.run()
    assert port.closed
