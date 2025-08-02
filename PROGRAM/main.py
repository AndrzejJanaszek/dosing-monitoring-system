import copy
from enum import Enum
from typing import Tuple, List

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
        self.isCollision: bool = False
        self.isRuning: bool = False

    def clear(self):
        self.measurement_start: Measurement = Measurement()
        self.measurement_end: Measurement = Measurement()
        self.isCollision: bool = False
        self.isRuning: bool = False

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

        if self.check_event_collision() or len(self.collision_points) % 2 == 1:
            # add collision_point
            self.collision_points.append(copy.deepcopy(measurement))

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

# tank list
# serialManager -> event
# databaseManager -> for handling function
def dosing_monitoring_thread(serialManager: __SerialManager, databaseManager, tanks: List[Tank]):
    while True:    
        serialManager.signal_data_event.wait()
        signalJSON = serialManager.get_signal_data()
        serialManager.signal_data_event.clear()
        signal = () # todo: convert from json to object

        # for each tank check state change
        # if state changed -> handle change
        for tank in tanks:
            for i, pin in enumerate(tank.pins):
                if signal[pin] != tank.statuses[i]:
                    # handle change
                    # read serial data - value
                    data = serialManager.get_tank_data(tank.port)
                    # todo: convert string to float
                    # todo contructor that sets timestamp
                    measurement = Measurement(data)

                    # ON / OFF --- START / END
                    if signal[pin]:
                        # start
                        tank.set_event_start(i, measurement)
                    else:
                        # end
                        tank.set_event_end(i, measurement)
                        # database manager save data
                        #   if event is collided

                        if not tank.check_event_collision():
                            tank.collision_points.clear()

                        # clear data ???

def main():
    # load config

    # init serialManager

    # init databaseManager

    # run cycle thread

    # run dosing thread
    
    
    pass


if __name__ == "__main__":
    main()