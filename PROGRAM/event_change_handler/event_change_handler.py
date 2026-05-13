from datetime import datetime

from threads.threads import parse_tank_data
from models.tank import Tank
from typing import List, Dict, Tuple
# from serial_manager.serial_manager import __SerialManager
from models.measurement import Measurement
# from database_manager.database_manager import __DatabaseManager
from models.dosage_event import EventType

class EventChangeHandler:
    def __init__(self, 
                 tanks: List[Tank],
                 serial_reader,
                 db_manager):
        
        self.serial_reader = serial_reader
        self.db_manager = db_manager

        # pin -> (tank, event_type)
        self.pin_map: Dict[int, Tuple[Tank, EventType]] = {}

        for tank in tanks:
            self.pin_map[tank.pins[0]] = (tank, EventType.FILL)
            self.pin_map[tank.pins[1]] = (tank, EventType.DISPENSE)
        
        pass

    def notify(self, target_status, pin):
        """
        Handle event change:\n
        set measurement data and save to db on event end
        target_status: 0 end | 1 start
        pin: number of pin that changed state/status 
        """

        if pin not in self.pin_map:
            raise ValueError(f"Nieznany pin: {pin}")

        tank, event_type = self.pin_map[pin]
    
        raw_value: str = self.serial_reader.get_tank_data(tank.port)
        # todo parse from str to int (measurement)
        measurement = Measurement(
            value=parse_tank_data(raw_value),
            time=datetime.now()
        )
        
        # start 
        if target_status == 1:   # -> start
            tank.set_event_start(event_type=event_type, measurement=measurement)

        elif target_status == 0:
            tank.set_event_end(event_type=event_type, measurement=measurement)
            self.db_manager.save_dosage(
                tank.events[event_type.value], tank.id
            )
            tank.events[event_type.value].clear()

        else:    
            raise ValueError(f"[Error]: target_status: {target_status}, not allowed (other than 0 or 1). Target status -> start or end of event")
