import contextlib
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

import structlog

from dms.acquisition.clock import NS_PER_S, Clock
from dms.acquisition.serial.framing import Framer
from dms.logs import events

FIRST_READ_BYTES = 1
IDLE_WAIT_S = 0.1
GARBAGE_LOG_EVERY = 100
GARBAGE_PREVIEW_BYTES = 64


class SerialPort(Protocol):
    def read(self, size: int, /) -> bytes: ...

    @property
    def in_waiting(self) -> int: ...

    def close(self) -> None: ...


type PortOpener = Callable[[], SerialPort]


class FrameOutcome(StrEnum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    REJECTED = "rejected"


class FrameHandler(Protocol):
    def handle(self, frame: bytes, wall_ns: int, mono_ns: int) -> FrameOutcome: ...


class SerialAdapter:
    def __init__(
        self,
        *,
        device_id: str,
        port_name: str,
        port_opener: PortOpener,
        framer: Framer,
        handler: FrameHandler,
        clock: Clock,
        stop_event: threading.Event,
        reconnect_delay_s: float,
        silence_timeout_s: float,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self._port_name = port_name
        self._port_opener = port_opener
        self._framer = framer
        self._handler = handler
        self._clock = clock
        self._stop_event = stop_event
        self._reconnect_delay_ns = round(reconnect_delay_s * NS_PER_S)
        self._silence_timeout_ns = round(silence_timeout_s * NS_PER_S)
        self._wait = wait if wait is not None else stop_event.wait
        self._logger = structlog.get_logger().bind(device_id=device_id, port=port_name)
        self._port: SerialPort | None = None
        self._next_open_attempt_ns = 0
        self._open_failure_logged = False
        self._window_start_ns = 0
        self._last_valid_ns = 0
        self._silence_origin_ns = 0
        self._silence_logged = False
        self._rejected_count = 0

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self.step()
        finally:
            self._close_port()

    def step(self) -> None:
        if self._port is None:
            self._try_open_port()
            return
        self._check_silence()
        if self._port is not None:
            self._read_and_handle(self._port)

    def _try_open_port(self) -> None:
        now_ns = self._clock.mono_ns()
        if now_ns < self._next_open_attempt_ns:
            self._wait(IDLE_WAIT_S)
            return
        try:
            self._port = self._port_opener()
        except OSError as error:
            self._next_open_attempt_ns = now_ns + self._reconnect_delay_ns
            if not self._open_failure_logged:
                self._logger.warning(events.PORT_OPEN_FAILED, error=str(error))
                self._open_failure_logged = True
            return
        self._open_failure_logged = False
        self._window_start_ns = now_ns
        self._logger.info(events.PORT_OPENED)

    def _check_silence(self) -> None:
        now_ns = self._clock.mono_ns()
        reference_ns = max(self._last_valid_ns, self._window_start_ns)
        if now_ns - reference_ns < self._silence_timeout_ns:
            return
        if not self._silence_logged:
            self._silence_origin_ns = reference_ns
            self._logger.warning(
                events.PORT_SILENCE, silence_timeout_s=self._silence_timeout_ns / NS_PER_S
            )
            self._silence_logged = True
        self._close_port()
        self._next_open_attempt_ns = now_ns

    def _read_and_handle(self, port: SerialPort) -> None:
        try:
            data = port.read(FIRST_READ_BYTES)
            if data:
                data += port.read(port.in_waiting)
        except OSError as error:
            self._logger.warning(events.PORT_DISCONNECTED, error=str(error))
            self._close_port()
            self._next_open_attempt_ns = self._clock.mono_ns() + self._reconnect_delay_ns
            return
        if not data:
            return
        wall_ns = self._clock.wall_ns()
        mono_ns = self._clock.mono_ns()
        rejected_before = self._framer.rejected_count
        for frame in self._framer.feed(data):
            outcome = self._handler.handle(frame, wall_ns, mono_ns)
            if outcome is FrameOutcome.ACCEPTED:
                self._mark_alive(mono_ns)
            elif outcome is FrameOutcome.REJECTED:
                self._note_garbage(frame)
        for _ in range(self._framer.rejected_count - rejected_before):
            self._note_garbage(b"")

    def _mark_alive(self, mono_ns: int) -> None:
        if self._silence_logged:
            self._logger.info(
                events.PORT_SILENCE_ENDED,
                duration_s=(mono_ns - self._silence_origin_ns) / NS_PER_S,
            )
            self._silence_logged = False
        self._last_valid_ns = mono_ns

    def _note_garbage(self, frame: bytes) -> None:
        self._rejected_count += 1
        self._logger.debug(events.PORT_GARBAGE, frame=frame[:GARBAGE_PREVIEW_BYTES])
        if self._rejected_count == 1 or self._rejected_count % GARBAGE_LOG_EVERY == 0:
            self._logger.warning(events.PORT_GARBAGE, rejected_count=self._rejected_count)

    def _close_port(self) -> None:
        if self._port is None:
            return
        with contextlib.suppress(OSError):
            self._port.close()
        self._port = None
        self._framer.reset()
