from header import *

# assumptions
# tank: 1
# event: 1

event_list = [
    [
        Event(0,5,100,EventType.IN),
        # Event(4,6,100,EventType.IN),
        Event(2,3,-100,EventType.OUT),
        Event(4,6,-100,EventType.OUT),
    ],
    # [
    #     Event(0,2,1000,EventType.IN),
    #     Event(4,6,-100,EventType.OUT),
    #     Event(8,10,-100,EventType.OUT),
    # ],
    # [
    #     Event(0,8,100,EventType.IN),
    #     Event(2,4,-100,EventType.OUT),
    #     Event(7,10,-100,EventType.OUT),
    # ],
]
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
event_list_standarised = [
    [
        Event(0,2,100,EventType.IN),    # in

        Event(0,2,100,EventType.OUT),   # out

        Event(2,6,100,EventType.IN),    #  |--in--|
        Event(0,4,100,EventType.OUT),   # out

        Event(0,4,100,EventType.IN),    # |--in--|
        Event(2,6,100,EventType.OUT),   #       out

        Event(0,6,100,EventType.IN),    # |--in--|
        Event(2,4,100,EventType.OUT),   #    out

        # -----------------------------
        Event(2,10,100,EventType.IN),   #  |--in----|
        Event(0,4,100,EventType.OUT),   # out   out
        Event(6,8,100,EventType.OUT),

        Event(0,8,100,EventType.IN),    # |--in----|
        Event(2,4,100,EventType.OUT),   #   out   out
        Event(6,10,100,EventType.OUT),

        Event(2,8,100,EventType.IN),    #  |--in--|
        Event(0,4,100,EventType.OUT),   # out    out
        Event(6,10,100,EventType.OUT),

        Event(2,10,100,EventType.IN),   #  |---in----|
        Event(0,4,100,EventType.OUT),   # out  out  out
        Event(6,8,100,EventType.OUT),
        Event(10,12,100,EventType.OUT),

        #----------------------------------------
        Event(0,10,100,EventType.IN),   # |----in----|
        Event(2,4,100,EventType.OUT),   #   out out 
        Event(6,8,100,EventType.OUT),

        Event(2,14,100,EventType.IN),   #  |----in-----|
        Event(0,4,100,EventType.OUT),   # out  out out 
        Event(6,8,100,EventType.OUT),
        Event(10,12,100,EventType.OUT),

        Event(0,12,100,EventType.IN),   # |----in-----|
        Event(2,4,100,EventType.OUT),   #  out out   out 
        Event(6,8,100,EventType.OUT),
        Event(10,14,100,EventType.OUT),

        Event(2,16,100,EventType.IN),   #  |----in-------|
        Event(0,4,100,EventType.OUT),   # out  out out  out 
        Event(6,8,100,EventType.OUT),
        Event(10,12,100,EventType.OUT),
        Event(14,18,100,EventType.OUT),


    ],
    # [
    #     Event(0,2,1000,EventType.IN),
    #     Event(4,6,-100,EventType.OUT),
    #     Event(8,10,-100,EventType.OUT),
    # ],
    # [
    #     Event(0,8,100,EventType.IN),
    #     Event(2,4,-100,EventType.OUT),
    #     Event(7,10,-100,EventType.OUT),
    # ],
]

tanks = [
    Tank(1000, 0, 1, None),
    # Tank(1000, 2, 3, None),
    # Tank(1000, 4, 5, None),
]


for i in range(0, len(tanks)):
    for e in event_list[i]:
        tanks[i].add_event(e)