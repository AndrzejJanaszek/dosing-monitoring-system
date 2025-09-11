from enum import Enum

class EventType(Enum):
    IN = 0
    OUT = 1

class Event:
    def __init__(self, start_time, end_time, factor, type:EventType, scenario_name = "None"):
        self.s_time = start_time
        self.e_time = end_time
        self.factor = factor
        self.type = type
        self.scenario_name: str

class Tank:
    def __init__(self, start_value, pin_in, pin_out, port):
        self.value = start_value
        self.statuses = [0,0]
        self.pins = [pin_in, pin_out]
        self.port = port
        self.events = [[],[]]
        self.event_indexes = [0, 0]
    
    def add_event(self, event:Event):
        self.events[event.type.value].append(event)

    def set_status(self, eventType:EventType, status):
        # TODO: type safety (0,1) for status
        self.statuses[eventType] = status
    
    def get_unfinished_events_count(self, eventType:EventType):
        return len(self.events[eventType]) - self.event_indexes[eventType]

    def get_current_event(self, eventType:EventType):
        return self.events[eventType][self.event_indexes[eventType]]
    
    def set_next_event(self, eventType:EventType):
        self.event_indexes[eventType] += 1

    def set_active_status(self, eventType:EventType):
        self.statuses[eventType] = 1
