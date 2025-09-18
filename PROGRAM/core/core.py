import json
import threading
from database_manager.database_manager import database_manager
from serial_manager.serial_manager import serial_manager
from models.tank import Tank
from models.transmition import TransmitionFormat
from threads import cycle_thread_fn, dosing_monitoring_thread_fn

def create_core():
    # load config
    with open("./config/config.json", "r") as f:
        config = json.load(f)


    # DB setup
    database_manager.setup_configuration(
        host=config["db"]["host"],
        user=config["db"]["user"],
        password=config["db"]["password"],
        database=config["db"]["database"],
    )
    database_manager.connect()


    # Tanks
    db_tanks = database_manager.get_tanks()
    existing_tanks = {(t["id"], t["tank_name"]) for t in db_tanks}
    tank_add_list = [
        {"id": t["id"], "name": t["name"]}
        for t in config["tanks"]
        if (t["id"], t["name"]) not in existing_tanks
    ]
    if tank_add_list:
        database_manager.save_tanks(tank_add_list)

    tanks = [Tank(**t) for t in config["tanks"]]


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


    # Serial manager
    serial_manager.setup_configuration(
        tank_serial_paths=[t.port for t in tanks],
        signal_serial_path=CONFIG_SIGNAL_PORT,
        serial_timeout=3,
        value_read_delay=0.1,
        signal_read_delay=0.1,
        tank_transmition_format=TransmitionFormat.ASCII,
        signal_transmition_format=TransmitionFormat.ASCII
    )
    serial_manager.setup_connections()
    serial_manager.start_threads()


    print("\nSerial Manager:")
    print("Połączenia:")
    print("- Tanks:", len(serial_manager.tank_serial_connections))
    print("- Signal:", True if serial_manager.signal_serial_connection else False)
    print()


    # Threads
    cycle_thread = threading.Thread(
        target=cycle_thread_fn,
        kwargs=dict(
            serial_manager=serial_manager,
            database_manager=database_manager,
            tanks=tanks,
            cycle_save_delay=config["CYCLE_SAVE_DELAY"],
        ),
        name="CycleSaverThread"
    )
    cycle_thread.start()

    dosing_thread = threading.Thread(
        target=dosing_monitoring_thread_fn,
        kwargs=dict(
            serial_manager=serial_manager,
            database_manager=database_manager,
            tanks=tanks,
        ),
        name="DosingMonitoringThread"
    )
    dosing_thread.start()

    return {
        "db": database_manager,
        "serial": serial_manager,
        "tanks": tanks
    }
