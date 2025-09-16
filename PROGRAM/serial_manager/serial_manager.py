import threading
from typing import List, Dict, Optional

from models.transmition import TransmitionFormat
from .serial_wrapper import SerialPortWrapper

class __SerialManager:
    # todo to jest z configa * podczas inicjalizacji obiektu

    def __init__(self):
        self.tank_serial_connections: List[SerialPortWrapper] = []
        self.signal_serial_connection: Optional[SerialPortWrapper] = None

        self.latest_data: Dict[str, str] = {}
        self.data_locks: Dict[str, threading.Lock] = {}

        self._stop_event = threading.Event()
        self.signal_data_event = threading.Event()

        self._threads: List[threading.Thread] = []

    def setup_configuration(self,
                 tank_serial_paths: Optional[List[str]],
                 signal_serial_path: Optional[str],
                 serial_timeout: Optional[float] = 3.0,
                 value_read_delay: Optional[float] = 0.1,
                 signal_read_delay: Optional[float] = 0.1,
                 tank_transmition_format: Optional[TransmitionFormat] = TransmitionFormat.ASCII,
                 signal_transmition_format: Optional[TransmitionFormat] = TransmitionFormat.ASCII):

        self.SERIAL_TIMEOUT = serial_timeout
        self.VALUE_READ_DELAY = value_read_delay
        self.SIGNAL_READ_DELAY = signal_read_delay

        self.TANK_TRANSMITION_FORMAT = tank_transmition_format
        self.SIGNAL_TRANSMITION_FORMAT = signal_transmition_format

        self.tank_serial_paths = tank_serial_paths
        self.signal_serial_path = signal_serial_path

    def setup_connections(self):
        for path in self.tank_serial_paths:
            conn = SerialPortWrapper(path, timeout=self.SERIAL_TIMEOUT)
            self.tank_serial_connections.append(conn)
            self.latest_data[path] = ""
            self.data_locks[path] = threading.Lock()

        self.signal_serial_connection = SerialPortWrapper(self.signal_serial_path, timeout=self.SERIAL_TIMEOUT)
        self.latest_data["signal"] = ""
        self.data_locks["signal"] = threading.Lock()

    def read_chunk(self, conn: SerialPortWrapper, transmition_format: TransmitionFormat) -> str:
        match transmition_format:
            case TransmitionFormat.ASCII:
                return conn.read_until(b'\x02', b'\x03')
            case TransmitionFormat.LINE:
                return conn.read_line()
            case TransmitionFormat.CRLF:
                return conn.read_until(b'\r\n')
            case _:
                raise ValueError(f"Unknown transmission format: {transmition_format}")

    def _tank_reading_loop(self, conn: SerialPortWrapper, path: str):
        while not self._stop_event.is_set():
            data = self.read_chunk(conn, transmition_format=self.TANK_TRANSMITION_FORMAT)
            if data:
                with self.data_locks[path]:
                    self.latest_data[path] = data
            threading.Event().wait(self.VALUE_READ_DELAY)

    def _signal_reading_loop(self):
        conn = self.signal_serial_connection
        while not self._stop_event.is_set():
            data = self.read_chunk(conn, transmition_format=self.SIGNAL_TRANSMITION_FORMAT)
            if data:
                with self.data_locks["signal"]:
                    self.latest_data["signal"] = data
                    self.signal_data_event.set()
            threading.Event().wait(self.SIGNAL_READ_DELAY)

    def start_threads(self):
        self._stop_event.clear()
        for i, conn in enumerate(self.tank_serial_connections):
            path = self.tank_serial_paths[i]
            t = threading.Thread(target=self._tank_reading_loop, args=(conn, path), daemon=True)
            t.start()
            self._threads.append(t)

        t = threading.Thread(target=self._signal_reading_loop, daemon=True)
        t.start()
        self._threads.append(t)

    def stop_threads(self):
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=2.0)

    def get_tank_data(self, path: str) -> Optional[str]:
        with self.data_locks.get(path, threading.Lock()):
            return self.latest_data.get(path)

    def get_signal_data(self) -> Optional[str]:
        with self.data_locks.get("signal", threading.Lock()):
            return self.latest_data.get("signal")

    def close(self):
        self.stop_threads()
        for conn in self.tank_serial_connections:
            conn.close()
        self.signal_serial_connection.close()

serial_manager = __SerialManager()