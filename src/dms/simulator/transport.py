import os
import pty
import select
import termios
import threading
import time
import tty
from collections.abc import Callable, Iterator, Mapping
from functools import partial
from pathlib import Path

from dms.acquisition.clock import NS_PER_S
from dms.simulator.encoders import BOARD_FRAME_END, banner_lines, encode_sample
from dms.simulator.scenario import Scenario
from dms.simulator.timeline import Sample, samples_from


class PseudoTerminal:
    def __init__(self, link: Path | None = None, greeting: bytes = b"") -> None:
        self._master_fd, slave_fd = pty.openpty()
        tty.setraw(slave_fd)
        self.path = Path(os.ttyname(slave_fd))
        os.close(slave_fd)
        os.set_blocking(self._master_fd, False)

        self.dropped_frames = 0
        self._greeting = greeting
        self._reader_connected = False
        self._link = link
        self._remainder = b""
        if link is not None:
            link.unlink(missing_ok=True)
            link.symlink_to(self.path)

    def send(self, data: bytes) -> None:
        if not self._has_reader():
            self._forget_unread_data()
            return

        if not self._reader_connected:
            self._reader_connected = True
            data = self._greeting + data

        self._write_remainder()
        if self._remainder:
            self.dropped_frames += 1
            return
        self._remainder = data
        self._write_remainder()

    def close(self) -> None:
        if self._link is not None:
            self._link.unlink(missing_ok=True)
        os.close(self._master_fd)

    def _has_reader(self) -> bool:
        poller = select.poll()
        poller.register(self._master_fd, select.POLLOUT)
        return not any(events & select.POLLHUP for _, events in poller.poll(0))

    def _forget_unread_data(self) -> None:
        if not self._reader_connected:
            return
        self._reader_connected = False
        self._remainder = b""

        reader_side_fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            termios.tcflush(reader_side_fd, termios.TCIFLUSH)
        finally:
            os.close(reader_side_fd)

    def _write_remainder(self) -> None:
        if not self._remainder:
            return
        try:
            written = os.write(self._master_fd, self._remainder)
        except BlockingIOError:
            written = 0
        self._remainder = self._remainder[written:]


def _resting_time(_: int) -> int:
    return 0


class SimulationRunner:
    def __init__(
        self,
        scenario: Scenario,
        link_dir: Path | None = None,
        now_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._scenario = scenario
        self._link_dir = link_dir
        self._now_ns = now_ns
        self._ports: dict[str, PseudoTerminal] = {}

        self._samples: Iterator[Sample]
        self._next_sample: Sample
        self._scenario_start_ns = 0

        self._start_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._wake = threading.Event()

        self._scenario_started = False
        self._running = False
        self._thread: threading.Thread | None = None
        self.scenario_finished = threading.Event()

    @property
    def ports(self) -> Mapping[str, PseudoTerminal]:
        return self._ports

    def open(self) -> None:
        if self._link_dir is not None:
            self._link_dir.mkdir(parents=True, exist_ok=True)

        board = self._scenario.layout.board
        banner = b"".join(line.encode("ascii") + BOARD_FRAME_END for line in banner_lines(board))
        for device_id in self._scenario.layout.device_ids():
            link = self._link_dir / device_id if self._link_dir is not None else None
            greeting = banner if device_id == board.id else b""
            self._ports[device_id] = PseudoTerminal(link, greeting)

        self._restart_samples(self._now_ns(), _resting_time)

    def start_scenario(self) -> None:
        self._start_requested.set()
        self._wake.set()

    def run(self) -> None:
        self._running = True
        try:
            while not self._stop_requested.is_set():
                timeout_s = self.step()
                self._wake.wait(timeout_s)
                self._wake.clear()
        finally:
            self._running = False
            self._close_ports()

    def step(self) -> float:
        now_ns = self._now_ns()
        if self._start_requested.is_set() and not self._scenario_started:
            self._begin_scenario(now_ns)

        while self._next_sample.at_ns <= now_ns:
            self._deliver(self._next_sample)
            self._next_sample = next(self._samples)

        self._mark_finished(now_ns)
        return max(0.0, (self._next_sample.at_ns - now_ns) / NS_PER_S)

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="simulation-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join()
        elif not self._running:
            self._close_ports()

    def _begin_scenario(self, now_ns: int) -> None:
        self._scenario_started = True
        self._scenario_start_ns = now_ns
        self._restart_samples(now_ns, partial(min, self._scenario.duration_ns))

    def _restart_samples(self, start_ns: int, state_time: Callable[[int], int]) -> None:
        self._samples = samples_from(self._scenario, start_ns, state_time)
        self._next_sample = next(self._samples)

    def _deliver(self, sample: Sample) -> None:
        device_id, data = encode_sample(sample, self._scenario.layout)
        self._ports[device_id].send(data)

    def _mark_finished(self, now_ns: int) -> None:
        if (
            self._scenario_started
            and now_ns - self._scenario_start_ns >= self._scenario.duration_ns
        ):
            self.scenario_finished.set()

    def _close_ports(self) -> None:
        while self._ports:
            _, port = self._ports.popitem()
            port.close()
