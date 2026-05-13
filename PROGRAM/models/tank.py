import copy
from typing import List, Tuple

from models.dosage_event import DosageEvent, EventType
from models.measurement import Measurement


class Tank:
    def __init__(self, pin_in, pin_out, port, name, id):
        self.statuses = [0,0]
        self.pins = [pin_in, pin_out]
        self.port = port
        self.name = name
        self.id = id

        self.events: Tuple[DosageEvent, DosageEvent] = (DosageEvent(), DosageEvent())
        self.events[0].type = EventType.IN
        self.events[1].type = EventType.OUT

        self.collision_points: List[Measurement] = []
        
        self.dispense_speed_factor: float = -1000.0
    
    def set_event_start(self, event_type: EventType, measurement: Measurement):
        # store data
        self.events[event_type].clear()
        self.events[event_type].measurement_start = copy.deepcopy(measurement)
        self.events[event_type].isRuning = True
        self.statuses[event_type] = 1

        # collision detection
        if self.check_event_collision():
            # add collision status to both events
            for event in self.events:
                event.isCollision = True

            # add collision_point
            self.collision_points.append(copy.deepcopy(measurement))

    def set_event_start(self, event_type: EventType, measurement: Measurement):
        # store data
        self.events[event_type].clear()
        self.events[event_type].measurement_start = copy.deepcopy(measurement)
        self.events[event_type].isRuning = True
        self.statuses[event_type] = 1

        # collision detection
        if self.check_event_collision():
            # add collision status to both events
            for event in self.events:
                event.isCollision = True

            # add collision_point
            self.collision_points.append(copy.deepcopy(measurement))
        
    def set_event_end(self, pin, measurement: Measurement):
        event_type: EventType = -1
        
        if self.pins[0] == pin:
            event_type = 0  # IN
        elif self.pins[1] == pin:
            event_type = 1  # OUT
        else:
            # Error
            raise Exception("[Error]: event_type can not be defined, because pin not found in self.pins.")
        
        # store data
        self.events[event_type].measurement_end = copy.deepcopy(measurement)
        self.events[event_type].calculate_parameters()  # value_difference, time_difference and dosing_speed_factor
        self.statuses[event_type] = 0

        # add collision_point
        if self.check_event_collision():
            self.collision_points.append(copy.deepcopy(measurement))

        # calc collision value difference
        self.calculate_collision_difference(event_type)

    # todo make two following methods priv
    def check_event_collision(self) -> bool: 
        # todo: change to:
        # return (self.events[0].isRuning and self.events[1].isRuning)

        if self.events[0].isRuning and self.events[1].isRuning:
            return True
        return False
    
    def calculate_collision_difference(self, event_type: EventType):
        if event_type == EventType.FILL.value:
            collisionTime = 0
            for i in range(0, len(self.collision_points), 2):
                collisionTime += (self.collision_points[i+1].time - self.collision_points[i].time).total_seconds()

            dispense_value = collisionTime * self.dispense_speed_factor
            print("collisionTime", collisionTime)
            print("self.dispense_speed_factor", self.dispense_speed_factor)
            print("dispense_value", dispense_value)
            value_diff = self.events[EventType.FILL.value].measurement_end.value - self.events[EventType.FILL.value].measurement_start.value
            print("value_diff", value_diff)
            calc_change = (-dispense_value) + value_diff    # *-1 becouse dispensed value is negative
            print("calc_change", calc_change)

            self.events[EventType.FILL.value].collision_difference = calc_change
        else:
            # factor * (dT) ==> factor * (time_end - time_start)
            self.events[EventType.DISPENSE.value].collision_difference = self.dispense_speed_factor * (self.events[EventType.DISPENSE.value].measurement_end.time - self.events[EventType.DISPENSE.value].measurement_start.time).total_seconds()
