from serial_manager.serial_manager import SerialManager
import time

tank_path = "/dev/pts/4"
signal_path = "/dev/pts/5"
sm = SerialManager([tank_path], signal_path, tank_transmition_delimiters=False, signal_transmition_delimiters=False)

sm.setup_connections()

sm.start_threads()

i = 0
step = 0.1
while i < 5:
    data = sm.get_tank_data(tank_path)
    print(data)
    i+=step
    time.sleep(step)

sm.close()