import copy
from enum import Enum
import re
from typing import Tuple, List
import json

from database_manager.database_manager import database_manager, __DatabaseManager
from models.dosage_event import EventType
from models.measurement import Measurement
from models.tank import Tank
from models.transmition import TransmitionFormat
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
            for event_type_int, pin in enumerate(tank.pins):
                if signal[pin] != tank.statuses[event_type_int]:
                    print("state change!")
                    # read tank value
                    data = serial_manager.get_tank_data(tank.port)
                    tank_value = parse_tank_data(data)
                    measurement = Measurement(tank_value)

                    # ON / OFF --- START / END
                    if signal[pin]:
                        # start
                        tank.set_event_start(measurement=measurement, event_type=event_type_int)
                    else:
                        # end
                        tank.set_event_end(measurement=measurement, event_type=event_type_int)

                        database_manager.save_dosage(tank.events[event_type_int], tank.id, event_type_int)

                        if event_type_int == EventType.FILL.value:
                            tank.collision_points.clear()

                        tank.events[event_type_int].clear()


def main():
    # load config
    CONFIG_PATH = "./config/config.json"
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)


    # init databaseManager
    database_manager.setup_configuration(
        host=config["db"]["host"],
        user=config["db"]["user"],
        password=config["db"]["password"],
        database=config["db"]["database"],
    )

    database_manager.connect()
    

    # tank list; config db relation check
    db_tanks = database_manager.get_tanks()

    existing_tanks = {(t["id"], t["tank_name"]) for t in db_tanks}

    tank_add_list = [
        {"id": t["id"], "name": t["name"]}
        for t in config["tanks"]
        if (t["id"], t["name"]) not in existing_tanks
    ]

    if tank_add_list:
        database_manager.save_tanks(tank_add_list)


    # load tanks from config 
    tanks = []
    for t in config["tanks"]:
        tanks.append(
            Tank(
            pin_in = t["pin_in"],
            pin_out = t["pin_out"],
            port = t["port"],
            name = t["name"],
            id = t["id"]
            )
        )


    # <START> DEV -- DEV -- DEV -- DEV -- DEV -- DEV -- DEV

    DEV_JSON_PORTS_PATH = './simulation/sender-path.json'

    with open(DEV_JSON_PORTS_PATH, 'r') as f:
        simulation_json = json.load(f)

    if len(tanks) < len(simulation_json["tank_ports"]):
        print("ERROR: (DEV) liczba portów wieksza niż liczba zbiorników z bazy")
        exit("ERROR: (DEV) liczba portów wieksza niż liczba zbiorników z bazy")



    for i, tank_port in enumerate(simulation_json["tank_ports"]):
        tanks[i].port = tank_port["slave_path"]
        tanks[i].pins[0] = 2*i
        tanks[i].pins[1] = 2*i+1

    # removes unnecessery tanks from list (tanks that not gonna be used)
    tanks = tanks[:len(simulation_json["tank_ports"])]

    CONFIG_SIGNAL_PORT = simulation_json["signal_port"]["slave_path"]

    # <END> DEV -- DEV -- DEV -- DEV -- DEV -- DEV -- DEV


    # init serial_manager
    serial_manager.setup_configuration(
        tank_serial_paths=[t.port for t in tanks],
        signal_serial_path=CONFIG_SIGNAL_PORT,
        serial_timeout=3,
        value_read_delay=0.1,
        signal_read_delay=0.1,
        tank_transmition_format=TransmitionFormat.ASCII,
        signal_transmition_format=TransmitionFormat.ASCII
    )

    # todo: zastanowic sie nad logika tego
    # czy jest sens wywolywac kilka funkcji
    serial_manager.setup_connections()
    serial_manager.start_threads()

    print("\nSerial Manager:")
    print("Połączenia:")
    print("- Tanks:", len(serial_manager.tank_serial_connections))
    print("- Signal:", True if serial_manager.signal_serial_connection else False)
    print()

    
    # run cycle thread
    # todo

    # run dosing thread
    dosing_monitoring_thread(
        serial_manager=serial_manager,
        database_manager=database_manager,
        tanks=tanks
    )


if __name__ == "__main__":
    # parse_signal_json('{"0": 1, "1": 0}')
    
    main()