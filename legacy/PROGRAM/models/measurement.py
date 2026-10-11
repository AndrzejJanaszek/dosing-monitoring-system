from datetime import datetime

class Measurement:
    def __init__(self, value: float = None, time: datetime = None):
        self.value: float = value
        self.time = time or datetime.now()

    def clear(self):
        self.value: float = None
        self.time = None

    def formatted_time(self) -> str:
        if self.time:
            return self.time.strftime("%Y-%m-%d %H:%M:%S")
        return "None"