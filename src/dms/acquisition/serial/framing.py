class Framer:
    def __init__(self, start: bytes, end: bytes, max_frame_length: int) -> None:
        self._start = start
        self._end = end
        self._max_frame_length = max_frame_length
        self._buffer = b""
        self._rejected_count = 0

    @property
    def rejected_count(self) -> int:
        return self._rejected_count

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer += chunk
        frames: list[bytes] = []
        while True:
            frame = self._extract_frame()
            if frame is None:
                break
            if len(frame) > self._max_frame_length:
                self._rejected_count += 1
            else:
                frames.append(frame)
        self._drop_overlong_buffer()
        return frames

    def reset(self) -> None:
        self._buffer = b""

    def _extract_frame(self) -> bytes | None:
        if self._start:
            start_index = self._buffer.find(self._start)
            if start_index < 0:
                keep = len(self._start) - 1
                self._buffer = self._buffer[len(self._buffer) - keep :] if keep else b""
                return None
            self._buffer = self._buffer[start_index:]
        body_offset = len(self._start)
        end_index = self._buffer.find(self._end, body_offset)
        if end_index < 0:
            return None
        frame = self._buffer[body_offset:end_index]
        self._buffer = self._buffer[end_index + len(self._end) :]
        return frame

    def _drop_overlong_buffer(self) -> None:
        if len(self._buffer) - len(self._start) > self._max_frame_length:
            self._buffer = b""
            self._rejected_count += 1
