from header import *

# assumptions
# tank: 1
# event: 1

event_list = [
    [
        Event(0,2,100,EventType.IN),
        Event(4,6,100,EventType.IN),
        Event(8,10,100,EventType.IN),
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