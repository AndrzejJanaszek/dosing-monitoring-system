import serial

class SerialPortWrapper:
    def __init__(self, port_path: str, timeout: float):
        self.port_path = port_path
        self.timeout = timeout
        self._connect()

    def _connect(self):
        self.serial = serial.Serial(self.port_path, timeout=self.timeout)

    def read_line(self) -> str:
        return self.serial.readline().decode("utf-8", errors="ignore").strip()

    def read_until(self, start_byte: bytes, end_byte: bytes) -> str:
        buffer = bytearray()
        started = False
        while True:
            byte = self.serial.read(1)
            if not byte:
                break  # timeout
            if byte == start_byte:
                buffer.clear()
                started = True
                continue
            if started:
                if byte == end_byte:
                    break
                buffer.extend(byte)
        return buffer.decode("utf-8", errors="ignore")

    def close(self):
        self.serial.close()
