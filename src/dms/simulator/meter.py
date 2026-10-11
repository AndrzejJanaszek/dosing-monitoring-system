import contextlib
import os
import pty
import threading
import tty
from pathlib import Path

from dms.acquisition.meters.dgtp import encode_dgtp_frame

SAWTOOTH_STEPS = 50


class MeterSimulator:
    def __init__(
        self, rate_hz: float, start_kg: int, step_kg: int, link: Path | None = None
    ) -> None:
        self._period_s = 1 / rate_hz
        self._start_kg = start_kg
        self._step_kg = step_kg
        self._link = link
        self._master_fd, self._slave_fd = pty.openpty()
        tty.setraw(self._slave_fd)
        os.set_blocking(self._master_fd, False)
        self.port_path = Path(os.ttyname(self._slave_fd))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if link is not None:
            link.unlink(missing_ok=True)
            link.symlink_to(self.port_path)

    def value_at(self, index: int) -> int:
        return self._start_kg + self._step_kg * (index % SAWTOOTH_STEPS)

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="meter-simulator", daemon=True)
        self._thread.start()

    def run(self) -> None:
        index = 0
        while not self._stop_event.wait(self._period_s):
            with contextlib.suppress(BlockingIOError):
                os.write(self._master_fd, encode_dgtp_frame(self.value_at(index)))
            index += 1

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
        if self._link is not None:
            self._link.unlink(missing_ok=True)
        os.close(self._master_fd)
        os.close(self._slave_fd)
