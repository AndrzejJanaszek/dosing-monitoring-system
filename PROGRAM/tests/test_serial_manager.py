from serial_manager.serial_manager import serialManager
import pytest
from serial import SerialException
import os
import pty


def test_singleton_instance():
    sm1 = serialManager
    sm2 = serialManager
    assert sm1 is sm2
    
def test_connection_setup():
    tank_master, tank_slave = pty.openpty()
    signal_master, signal_slave = pty.openpty()
    tank_path = os.ttyname(tank_slave)
    signal_path = os.ttyname(signal_slave)

    sm = serialManager
    sm.setup_configuration([tank_path], signal_path)

    try:
        sm.setup_connections()
        assert len(sm.tank_serial_connections) == 1, "Serial 'tank' connection count unexpected"
        assert sm.signal_serial_connection is not None , "Serial 'signal' connection is None"
    finally:
        os.close(tank_master)
        os.close(tank_slave)
        os.close(signal_master)
        os.close(signal_slave)

def test_connection_setup_failure():
    sm = serialManager
    sm.setup_configuration(["/invalid/port"], "/invalid/signal")
    with pytest.raises(SerialException):
        sm.setup_connections()
