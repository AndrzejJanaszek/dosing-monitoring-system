import copy
from enum import Enum
import re
from typing import Tuple, List
import json

from database_manager.database_manager import database_manager, __DatabaseManager
from models.dosage_event import EventType
from models.measurement import Measurement
from models.tank import Tank
from serial_manager.serial_manager import serial_manager, __SerialManager


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
                    print("state change!")
                    # read tank value
                    data = serial_manager.get_tank_data(tank.port)
                    tank_value = parse_tank_data(data)
                    # todo contructor that sets timestamp
                    measurement = Measurement(tank_value)

                    # ON / OFF --- START / END
                    if signal[pin]:
                        # start
                        tank.set_event_start(measurement=measurement, event_type=i)
                    else:
                        # end
                        tank.set_event_end(measurement=measurement, event_type=i)

                        database_manager.save_dosage(tank.events[i])

                        if i == EventType.FILL.value:
                            tank.collision_points.clear()
                        # clear data ???

def main():
    # load config
    # mock
    tanks = [
        Tank(start_value=1000, 
                 pin_in=0, 
                 pin_out=1,
                 port="/dev/pts/4")
    ]
    CONFIG_SIGNAL_PORT = "/dev/pts/5"
        

    # init serial_manager
    # todo zmienic delimiters na mode: ascii, line, \n\r
    serial_manager.setup_configuration(
        tank_serial_paths=[t.port for t in tanks],
        signal_serial_path=CONFIG_SIGNAL_PORT,
        serial_timeout=3,
        value_read_delay=0.1,
        signal_read_delay=0.1,
        tank_transmition_delimiters=True,
        signal_transmition_delimiters=True
    )

    # todo:  zmiana nazwy w chuj do zmiany pewnie xd
    # todo: logika ogólnie
    serial_manager.setup_connections()
    serial_manager.start_threads()

    # init databaseManager
    database_manager.setup_configuration(
        host="",
        user="",
        password="",
        database=""
    )
    # run cycle thread
    # todo

    # run dosing thread
    # todo
    dosing_monitoring_thread(
        serial_manager=serial_manager,
        database_manager=database_manager,
        tanks=tanks
    )


if __name__ == "__main__":
    # parse_signal_json('{"0": 1, "1": 0}')
    
    main()