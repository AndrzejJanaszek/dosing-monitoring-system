from header import *

from event_config import tanks

SIMULATION_TIME_END = 10
SIMULATION_TIME_STEP = 0.1

EVENT_TYPES = [EventType.IN.value, EventType.OUT.value]

time = 0
while time <= SIMULATION_TIME_END:
    # EVENT CHANGES HANDLING
    for tank in tanks:
        for e_type in EVENT_TYPES:
            tank.set_status(e_type, 0)

            while tank.get_unfinished_events_count(e_type) > 0:
                if time > tank.get_current_event(e_type).e_time:
                    # current event ended
                    tank.set_next_event(e_type)
                    continue

                if time > tank.get_current_event(e_type).s_time:
                    tank.set_active_status(e_type)
                    tank.value += tank.get_current_event(e_type).factor * SIMULATION_TIME_STEP
                    # print(tank.value)
                break

    # SENDING DATA 
    print(f"{time:6.2f}", end=" | ")
    for tank in tanks:
        print(f"{tank.value:8.2f}", end=" | ") 
    print()

    print(f"{'':6}", end=" | ")
    for tank in tanks:
        print("".join(f"{int(s):^4}" for s in tank.statuses), end=" | ")
    print()



    # LOOP END TIME INCREMENT
    time += SIMULATION_TIME_STEP





