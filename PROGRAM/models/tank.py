import copy
from typing import List, Tuple

from models.dosage_event import DosageEvent, EventType
from models.measurement import Measurement


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

    def set_event_end(self, event_type: EventType, measurement: Measurement):
        # store data
        self.events[event_type].measurement_end = copy.deepcopy(measurement)
        self.events[event_type].calculate_value_difference()
        self.statuses[event_type] = 0

        # add collision_point
        if self.check_event_collision():
            self.collision_points.append(copy.deepcopy(measurement))

        # calc value difference
        # self.events[event_type].difference = self.events[event_type].measurement_end.value - self.events[event_type].measurement_start.value
        self.events[event_type].calculate_value_difference()
        self.calculate_collision_difference(event_type)

    # todo make two following methods priv
    def check_event_collision(self) -> bool: 
        if self.events[0].isRuning and self.events[1].isRuning:
            return True
        return False
    
    def calculate_collision_difference(self, event_type: EventType):
        if event_type == EventType.FILL.value:
            collisionTime = 0
            for i in range(0, len(self.collision_points), 2):
                collisionTime += (self.collision_points[i+1].time - self.collision_points[i].time).total_seconds()

            dispense_value = collisionTime * self.dispense_speed_factor
            value_diff = self.events[EventType.FILL.value].measurement_end.value - self.events[EventType.FILL.value].measurement_start.value
            calc_change = dispense_value + value_diff

            self.events[EventType.FILL.value].collision_difference = calc_change
        else:
            # factor * (dT) ==> factor * (time_end - time_start)
            self.events[EventType.DISPENSE.value].collision_difference = self.dispense_speed_factor * (self.events[EventType.DISPENSE.value].measurement_end.time - self.events[EventType.DISPENSE.value].measurement_start.time).total_seconds()
