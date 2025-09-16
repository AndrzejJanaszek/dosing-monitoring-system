import copy
import random
from typing import List
from header import *

from scenario import Scenario, fundamental_scenerio_list, gr_1_scenarios, gr_2_scenarios, gr_3_scenarios

_TANK_STARTING_VALUE_ = 1000

_SIMULATION_TIME_ = 10

_SEPARATION_TIME_ = 2

tanks = []

def tank_per_scenerio():
    global _SIMULATION_TIME_
    _SIMULATION_TIME_ = max(sc.time_length for sc in fundamental_scenerio_list)
    # for each scenerio
    for i, sc in enumerate(fundamental_scenerio_list):
        t = Tank(
                start_value=_TANK_STARTING_VALUE_, 
                pin_in=2*i, 
                pin_out=2*i+1,
                port=None)

        # for each event
        for ev in sc.event_list:
            ev.scenario_name = sc.name
            t.add_event(ev)

        tanks.append(t)

def one_tank_multiple_scenarios():
    global _SIMULATION_TIME_
    t = Tank(
                start_value=_TANK_STARTING_VALUE_, 
                pin_in=0, 
                pin_out=1,
                port=None)

    time_offset = 0

    # for each scenerio
    for sc in fundamental_scenerio_list:
        # for each event
        for ev in sc.event_list:
            ev.scenario_name = sc.name
            ev.s_time += time_offset
            ev.e_time += time_offset

            t.add_event(ev)

        time_offset += sc.time_length + _SEPARATION_TIME_
    
    _SIMULATION_TIME_ = time_offset
    tanks.append(t)
    
def n_tanks_n_scenerios(tank_number: int, scenerio_list: List[Scenario], shuffle: bool = False):
    global _SIMULATION_TIME_
    time_offset = 0
    for sc in scenerio_list:
        time_offset += sc.time_length + _SEPARATION_TIME_
    _SIMULATION_TIME_ = time_offset

    for n in range(0,tank_number):
        t = Tank(
                    start_value=_TANK_STARTING_VALUE_, 
                    pin_in=2*n, 
                    pin_out=2*n+1,
                    port=None)

        time_offset = 0

        if shuffle:
            random.shuffle(scenerio_list)

        # for each scenerio
        for sc in scenerio_list:
            # for each event
            for ev in sc.event_list:
                ev_copy = copy.deepcopy(ev)   # nowy obiekt event
                ev_copy.scenario_name = sc.name
                ev_copy.s_time += time_offset
                ev_copy.e_time += time_offset

                t.add_event(ev_copy)

            time_offset += sc.time_length + _SEPARATION_TIME_
        
        tanks.append(t)





# print("len(gr_1_scenarios): ", len(gr_1_scenarios))
# print("len(gr_2_scenarios): ", len(gr_2_scenarios))
# print("len(gr_3_scenarios): ", len(gr_3_scenarios))
# print("len(fundamental_scenerio_list): ", len(fundamental_scenerio_list))


# n_tanks_n_scenerios(tank_number=5, scenerio_list=fundamental_scenerio_list, shuffle=False)

n_tanks_n_scenerios(tank_number=1, scenerio_list=gr_1_scenarios, shuffle=False)

# n_tanks_n_scenerios(tank_number=5, scenerio_list=gr_2_scenarios, shuffle=False)

# n_tanks_n_scenerios(tank_number=5, scenerio_list=gr_3_scenarios, shuffle=False)

# tank_per_scenerio()

# one_tank_multiple_scenarios()