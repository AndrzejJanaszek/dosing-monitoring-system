from serial_manager.serial_manager import SerialManager

import pytest

from serial import SerialException


@pytest.fixture(autouse=True)
def reset_singleton():
    yield
    SerialManager._instance = None


def test_singleton_instance():
    sm1 = SerialManager(["/dev/pts/4"], "/dev/pts/9")
    sm2 = SerialManager(["/dev/pts/4"], "/dev/pts/9")
    assert sm1 is sm2

def test_connection_setup():
    tank_path = "/dev/pts/4"
    signal_path = "/dev/pts/5"
    sm = SerialManager([tank_path], signal_path)

    sm.setup_connections()

def test_connection_setup_failure():
    sm = SerialManager(["/invalid/port"], "/invalid/signal")
    with pytest.raises(SerialException):
        sm.setup_connections()
