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
        self.value_difference = 0
        self.collision_difference = 0
        self.time_difference = 0
        self.dosing_speed_factor = 0
        self.isCollision: bool = False
        self.isRuning: bool = False

    def clear(self):
        self.measurement_start: Measurement = Measurement()
        self.measurement_end: Measurement = Measurement()
        self.value_difference = 0
        self.collision_difference = 0
        self.time_difference = 0
        self.dosing_speed_factor = 0
        self.isCollision: bool = False
        self.isRuning: bool = False


    def calculate_parameters(self):
        self._calculate_value_difference()
        self._calculate_time_difference()
        self._calculate_dosing_speed_factor()

    def _calculate_value_difference(self):
        self.value_difference = self.measurement_end.value - self.measurement_start.value
        return self.value_difference
    
    def _calculate_time_difference(self):
        self.time_difference = (self.measurement_end.time - self.measurement_start.time).total_seconds()
        return self.time_difference
    
    def _calculate_dosing_speed_factor(self):
        if self.isCollision:
            self.dosing_speed_factor = 0
            return 0
        
        self.dosing_speed_factor = self.value_difference / self.time_difference
        return self.dosing_speed_factor
    
    def print_state(self):
        fmt = "%Y-%m-%d %H:%M:%S"
        start_time_str = self.measurement_start.time.strftime(fmt) if self.measurement_start.time else "None"
        end_time_str = self.measurement_end.time.strftime(fmt) if self.measurement_end.time else "None"

        print(f"M_S: v: {self.measurement_start.value}; t: {start_time_str}")
        print(f"M_E: v: {self.measurement_end.value}; t: {end_time_str}")
        print(f"value_diff: {self.value_difference}")
        print(f"col_diff: {self.collision_difference}")
        print(f"time_diff: {self.time_difference}")
        print(f"dosing_speed_factor: {self.dosing_speed_factor}")
        print(f"isCollision: {self.isCollision}")
        print(f"isRunning: {self.isRuning}")


