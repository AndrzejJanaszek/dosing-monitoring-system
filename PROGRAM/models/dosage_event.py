from enum import Enum

from models.measurement import Measurement


class EventType(Enum):
    IN = 0
    OUT = 1
    FILL = 0
    DISPENSE = 1

class DosageEvent:
    def __init__(self):
        self.measurement_start: Measurement = Measurement()
        self.measurement_end: Measurement = Measurement()
        self.difference = 0
        self.collision_difference = 0
        self.isCollision: bool = False
        self.isRuning: bool = False

    def clear(self):
        self.measurement_start: Measurement = Measurement()
        self.measurement_end: Measurement = Measurement()
        self.difference = 0
        self.collision_difference = 0
        self.isCollision: bool = False
        self.isRuning: bool = False

    def calculate_value_difference(self):
        self.difference = self.measurement_end.value - self.measurement_start.value
        return self.difference
    
    def print_state(self):
        fmt = "%Y-%m-%d %H:%M:%S"
        start_time_str = self.measurement_start.time.strftime(fmt) if self.measurement_start.time else "None"
        end_time_str = self.measurement_end.time.strftime(fmt) if self.measurement_end.time else "None"

        print(f"M_S: v: {self.measurement_start.value}; t: {start_time_str}")
        print(f"M_E: v: {self.measurement_end.value}; t: {end_time_str}")
        print(f"diff: {self.difference}")
        print(f"col_diff: {self.collision_difference}")
        print(f"isCollision: {self.isCollision}")
        print(f"isRunning: {self.isRuning}")


