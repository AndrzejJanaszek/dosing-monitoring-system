import copy
from enum import Enum
import re
from typing import Tuple, List
import json

from PROGRAM.database_manager.database_manager import __DatabaseManager
from PROGRAM.serial_manager.serial_manager import __SerialManager

class Measurement:
    def __init__(self):
        self.value: float
        self.time

    def clear(self):
        self.value: float = None
        self.time = None

class DosageEvent:
    def __init__(self):
        self.measurement_start: Measurement = 0
        self.measurement_end: Measurement = 0
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

    def calc_and_set_value_difference(self):
        self.difference = self.measurement_end.value - self.measurement_end.start
        return self.difference

class EventType(Enum):
    IN = 0
    OUT = 1
    FILL = 0
    DISPENSE = 1

class Tank:
    def __init__(self, start_value, pin_in, pin_out, port):
        self.value = start_value
        self.statuses = [0,0]
        self.pins = [pin_in, pin_out]
        self.port = port

        self.events: Tuple[DosageEvent, DosageEvent] = (DosageEvent(), DosageEvent())
        self.collision_points: List[Measurement] = []
        
        self.dispense_speed_factor: float = 1.0
    
    def set_event_start(self, event_type: EventType, measurement: Measurement):
        self.events[event_type].clear()

        self.events[event_type].measurement_start = copy.deepcopy(measurement)
        self.events[event_type].isRuning = True

        if self.check_event_collision():
            for event in self.events:
                event.isCollision = True

            # add collision_point
            self.collision_points.append(copy.deepcopy(measurement))

    def set_event_end(self, event_type: EventType, measurement: Measurement):
        self.events[event_type].measurement_end = copy.deepcopy(measurement)
        self.events[event_type].calc_and_set_value_difference()

        # add collision_point
        if self.check_event_collision() or len(self.collision_points) % 2 == 1:
            self.collision_points.append(copy.deepcopy(measurement))

        # calculate collision_difference
        if self.events[event_type].isCollision:
            if event_type == EventType.FILL:
                # diff = self.get_calculated_fill_value_difference()
                self.events[EventType.FILL].collision_difference = self.get_calculated_fill_value_difference()
            else:
                self.events[EventType.DISPENSE].collision_difference = self.get_calculated_dispense_value_difference()

    def check_event_collision(self) -> bool: 
        if self.event_dispense.isRuning and self.event_fill.isRuning:
            return True
        return False
    
    def get_calculated_dispense_value_difference(self):
        return self.dispense_speed_factor * (self.events[EventType.DISPENSE].measurement_end.time - self.events[EventType.DISPENSE].measurement_start.time)

    def get_calculated_fill_value_difference(self):
        collisionTime = 0
        for i in range(0, len(self.collision_points), 2):
            collisionTime += self.collision_points[i+1].time - self.collision_points[i].time

        dispense_value = collisionTime * self.dispense_speed_factor
        value_diff = self.events[EventType.FILL].measurement_end.value - self.events[EventType.FILL].measurement_start.value
        calc_change = dispense_value + value_diff

        return calc_change


def handle_tank_state_change(tank):
    # collision check
    # store data
    # 
    # if END save data -> saveEvent() /or/ saveDosage()
    # end clear stored data
    # if this is ONLY runing event than clear collision point list
    
    
    pass

def parse_signal_json(signal_json: str) -> dict[int, int]:
    try:
        data = json.loads(signal_json)
        return {int(k): int(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"Błąd parsowania sygnału: {e}")
        return {}
    
def parse_tank_data(tank_data: str) -> float:
    try:
        match = re.search(r"[-+]?\d*\.?\d+", tank_data)
        if match:
            return float(match.group())
        else:
            raise ValueError("Brak liczby w ciągu")
    except Exception as e:
        print(f"Błąd parsowania danych: {e}")
        return 0.0

# tank list
# serialManager -> event
# databaseManager -> for handling function\
def dosing_monitoring_thread(serial_manager: __SerialManager, database_manager: __DatabaseManager, tanks: List[Tank]):
    while True:    
        # read signal data
        serial_manager.signal_data_event.wait()
        signal_json = serial_manager.get_signal_data()
        serial_manager.signal_data_event.clear()
        signal = parse_signal_json(signal_json)

        # for each tank check state change
        # and handle change
        for tank in tanks:
            for i, pin in enumerate(tank.pins):
                if signal[pin] != tank.statuses[i]:
                    # handle change

                    # read tank value
                    data = serial_manager.get_tank_data(tank.port)
                    tank_value = parse_tank_data(data)
                    # todo contructor that sets timestamp
                    measurement = Measurement(tank_value)

                    # ON / OFF --- START / END
                    if signal[pin]:
                        # start
                        tank.set_event_start(measurement, event_type=i)
                    else:
                        # end
                        tank.set_event_end(measurement, event_type=i)

                        database_manager.save_dosage(tank.events[i])

                        if i == EventType.FILL:
                            tank.collision_points.clear()
                        # clear data ???

def main():
    # load config

    # init serial_manager

    # init databaseManager

    # run cycle thread

    # run dosing thread
    
    
    pass


if __name__ == "__main__":
    parse_signal_json('{"0": 1, "1": 0}')
    
    main()