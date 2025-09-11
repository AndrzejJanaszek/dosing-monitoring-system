from header import *

from scenario import Scenario, fundamental_scenerio_list

_TANK_STARTING_VALUE_ = 1000

_SIMULATION_TIME_ = 10

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

        time_offset += sc.time_length
    
    _SIMULATION_TIME_ = time_offset
    tanks.append(t)
    

# todo
# zrobić obiekty typu scenariusz i zapisać poniższe scenariusze
# odpalić zbiornik dla każdego scenariusza jako test
# a wczesniej przygotowac srodowskio testowe do tego
# 1. wszsytkie scenariusze - odpala dla każdego osobny zbiornik
# 2. losowe scenariusze - losuje N scenariuszy; opcja osobne zbiorniki: bool 
# (jeżeli True odpala na osobnych zbiornikach, jeżeli False
# odpala na jednym)
# 3. wybrany schemat testowania:
# konfigurujemy ile zbiorników i z jakimi scenariuszami
# do tego możliwość zrobienia customowego scenariusza
#
# do tego musi być zapis ścieżek do pliku i w programie głównym moduł
# odczytujący je (ten config) bo bez sensu byłoby ręczne wklepywanie tego

# tank_per_scenerio()
one_tank_multiple_scenarios()