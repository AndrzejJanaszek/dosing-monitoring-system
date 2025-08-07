import time
from serial_manager.serial_manager import serial_manager
from simulation.header import Tank


def test_signal_read():
    tanks = [
        Tank(start_value=1000, 
                 pin_in=0, 
                 pin_out=1,
                 port="/dev/pts/4")
    ]
    CONFIG_SIGNAL_PORT = "/dev/pts/5"

    serial_manager.setup_configuration(
        tank_serial_paths=[t.port for t in tanks],
        signal_serial_path=CONFIG_SIGNAL_PORT,
        serial_timeout=3,
        value_read_delay=1,
        signal_read_delay=1,
        tank_transmition_delimiters=True,
        signal_transmition_delimiters=True
    )

    # todo:  zmiana nazwy w chuj do zmiany pewnie xd
    # todo: logika ogólnie
    serial_manager.setup_connections()
    serial_manager.start_threads()

    while True:
        data = serial_manager.get_signal_data()
        print("data: ", data)
        time.sleep(0.5)

test_signal_read()