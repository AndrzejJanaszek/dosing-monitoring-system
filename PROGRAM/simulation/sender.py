import os
import json
from time import sleep
import pty
from pathlib import Path
import copy
import threading



from header import *

from event_config import tanks as imported_tanks
        
class TransmissionMode(Enum):
    LINE = "line"
    ASCII = "ascii"

def send_tank_value(tanks, mode: TransmissionMode = TransmissionMode.LINE):
    for tank in tanks:
        msg = f"{tank.value}"
        encoded_msg = encode_message(msg, mode)
        os.write(tank.port, encoded_msg)


def send_signals(port, tanks, mode: TransmissionMode = TransmissionMode.LINE):
    output = {}

    for tank in tanks:
        for pin, status in zip(tank.pins, tank.statuses):
            output[str(pin)] = status

    json_str = json.dumps(output, separators=(',', ':'), indent=None)
    encoded_msg = encode_message(json_str, mode)
    os.write(port, encoded_msg)


def encode_message(msg: str, mode: TransmissionMode = TransmissionMode.LINE) -> bytes:
    if mode == TransmissionMode.ASCII:
        return b"\x02" + msg.encode("utf-8") + b"\x03"
    else:
        return (msg + "\n").encode("utf-8")

def create_tank_connections():
    tank_ports = []
    for i, tank in enumerate(imported_tanks):
        master_fd, slave_fd = pty.openpty()
        slave_path = os.ttyname(slave_fd)
        # debug print
        # print(f"Tank {i}: master_fd={master_fd}, slave_path={slave_path}")
        tank.port = master_fd  # przypisz master_fd do portu, do zapisu
        tank_ports.append({"id": i, "slave_path": slave_path})

    return tank_ports

def create_signal_connection():
    # Tworzymy pty dla signal_port
    signal_master_fd, signal_slave_fd = pty.openpty()
    signal_slave_path = os.ttyname(signal_slave_fd)
    # debug print
    # print(f"Signal port: master_fd={signal_master_fd}, slave_path={signal_slave_path}")

    signal_port = {
        "master_fd": signal_master_fd,
        "slave_path": signal_slave_path
    }

    return signal_port

def save_connections(tank_ports, signal_slave_path, json_path):
    with open(json_path, "w") as f:
        json.dump({
            "tank_ports": tank_ports,
            "signal_port": {"slave_path": signal_slave_path}
        }, f, indent=2)

def print_connections(tank_ports, signal_slave_path):
    print("\n[CONN] List of connections:")
    for port in tank_ports:
        print("[CONN] port: ", port)
    
    print("[CONN] signal port: ", signal_slave_path)
    print()

def close_connections(tanks, signal_port):
    for tank in tanks:
        os.close(tank.port)
    os.close(signal_port["master_fd"])

start_event = threading.Event()
stop_event = threading.Event()
restart_event = threading.Event()

def simulation(signal_port):
    print("[SIM] Waiting for start...")
    while not stop_event.is_set():
        if not start_event.wait(timeout=1):
            continue

        start_event.clear()
        print("[SIM] Simulation started")

        tanks = copy.deepcopy(imported_tanks)

        SIMULATION_TIME_END = 10
        SIMULATION_TIME_STEP = 0.25
        EVENT_TYPES = [EventType.IN.value, EventType.OUT.value]

        # todo jeszcze jeden tryb \n\r czy jakos tak
        SIGNAL_TRANSITION_MODE = TransmissionMode.ASCII
        TANK_TRANSITION_MODE = TransmissionMode.ASCII

        # DEBUG_MSG_TIME = 2  # time in seconds

        # try:
        sim_time = 0
        # msg_time = 0
        while sim_time <= SIMULATION_TIME_END:
            if restart_event.is_set():
                print("[SIM] Restarting simulation")
                restart_event.clear()
                start_event.set()
                break

            # if msg_time >= DEBUG_MSG_TIME:
            #     print("[SIM] running...")
            #     msg_time = 0

            # EVENT CHANGES HANDLING
            for tank in tanks:
                for e_type in EVENT_TYPES:
                    tank.set_status(e_type, 0)

                    while tank.get_unfinished_events_count(e_type) > 0:
                        if sim_time > tank.get_current_event(e_type).e_time:
                            # current event ended
                            tank.set_next_event(e_type)
                            continue

                        if sim_time > tank.get_current_event(e_type).s_time:
                            tank.set_active_status(e_type)
                            tank.value += tank.get_current_event(e_type).factor * SIMULATION_TIME_STEP
                            # print(tank.value)
                        break

            # SENDING DATA 
            send_tank_value(tanks, TANK_TRANSITION_MODE)

            send_signals(signal_port["master_fd"], tanks, SIGNAL_TRANSITION_MODE)


            # LOOP END TIME INCREMENT
            sim_time += SIMULATION_TIME_STEP
            # msg_time += SIMULATION_TIME_STEP
            sleep(SIMULATION_TIME_STEP)

        print("[SIM] simulation time end")
        print("[SIM] to start new simulation type 'start' command")

    print("[SIM] Simulation ended")
    if 'tanks' in locals():
        print("[SIM] closing connections")
        close_connections(tanks, signal_port)
        print("[SIM] connections closed")

def command_listener():
    print("[CMD] List of available commands:")
    print("[CMD] - start\t\tstarts simulation")
    print("[CMD] - restart\t\trestarts simulation")
    print("[CMD] - exit\t\texits testing program")

    while True:
        cmd = input("> ").strip().lower()
        if cmd == "start":
            print("[CMD] start")
            start_event.set()
        elif cmd == "restart":
            print("[CMD] restart")
            restart_event.set()
        elif cmd == "exit":
            print("[CMD] exit")
            stop_event.set()
            break
        else:
            print("[CMD] unknown")

def main():
    print("Sender main()")

    ####### INIT #######
    BASE_DIR = Path(__file__).resolve().parent
    SENDER_PATH_JSON = BASE_DIR / "sender-path.json"

    ###### SERIAL CONNECTIONS ######

    # creates connections and save ports to tank.port
    tank_ports = create_tank_connections()  # uses imported_tanks
    signal_port = create_signal_connection()

    save_connections(tank_ports, signal_port["slave_path"], SENDER_PATH_JSON)
    print_connections(tank_ports, signal_port["slave_path"])

    ##################### SIMULATION ######################

    sim_thread = threading.Thread(target=simulation, args=(signal_port,))
    sim_thread.start()
    command_listener()
    sim_thread.join()

    print("[MAIN] main exit")
    # simulation(signal_port=signal_port)


if __name__ == "__main__":
    main()
