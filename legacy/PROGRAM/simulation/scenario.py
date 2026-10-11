from typing import List
from header import *

class Scenario:
    def __init__(self, name: str, event_list: List[Event] ):
        self.name: str = name
        self.event_list: List[Event] = event_list
        self.time_length: float = self.calc_time_length()

    def calc_time_length(self):
        return max((e.e_time for e in self.event_list), default=0)

gr_1_scenarios = [
    Scenario(
        "IN", 
        [Event(0,2,100,EventType.IN)]
        )
    ,
    Scenario(
        "OUT", 
        [Event(0,2,-100,EventType.OUT)]
        )
    ,
    Scenario(
        "FRONT",
        [
            Event(2,6,100,EventType.IN),    #  |--in--|
            Event(0,4,-100,EventType.OUT),   # out
        ])
    ,
    Scenario(
        "BACK",
        [
            Event(0,4,100,EventType.IN),    # |--in--|
            Event(2,6,-100,EventType.OUT),   #       out
        ])
    ,
    Scenario(
        "INNER",
        [
            Event(0,6,100,EventType.IN),    # |--in--|
            Event(2,4,-100,EventType.OUT),   #    out
        ])
]

gr_2_scenarios = [
    Scenario(
        "FRONT-INNER",
        [
            Event(2,10,100,EventType.IN),   #  |--in----|
            Event(0,4,-100,EventType.OUT),   # out   out
            Event(6,8,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "INNER-OUT",
        [
            Event(0,8,100,EventType.IN),    # |--in----|
            Event(2,4,-100,EventType.OUT),   #   out   out
            Event(6,10,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "FRONT-BACK",
        [
            Event(2,8,100,EventType.IN),    #  |--in--|
            Event(0,4,-100,EventType.OUT),   # out    out
            Event(6,10,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "FRONT-INNER-BACK",
        [
            Event(2,10,100,EventType.IN),   #  |---in----|
            Event(0,4,-100,EventType.OUT),   # out  out  out
            Event(6,8,-100,EventType.OUT),
            Event(10,12,-100,EventType.OUT),
        ])
]

gr_3_scenarios = [
    Scenario(
        "M_INNER",
        [
            Event(0,10,100,EventType.IN),   # |----in----|
            Event(2,4,-100,EventType.OUT),   #   out out 
            Event(6,8,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "FRONT-M_INNER",
        [
            Event(2,14,100,EventType.IN),   #  |----in-----|
            Event(0,4,-100,EventType.OUT),   # out  out out 
            Event(6,8,-100,EventType.OUT),
            Event(10,12,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "M_INNER-BACK",
        [
            Event(0,12,100,EventType.IN),   # |----in-----|
            Event(2,4,-100,EventType.OUT),   #  out out   out 
            Event(6,8,-100,EventType.OUT),
            Event(10,14,-100,EventType.OUT),
        ])
    ,
    Scenario(
        "FRONT-M_INNER-BACK",
        [
            Event(2,16,100,EventType.IN),   #  |----in-------|
            Event(0,4,-100,EventType.OUT),   # out  out out  out 
            Event(6,8,-100,EventType.OUT),
            Event(10,12,-100,EventType.OUT),
            Event(14,18,-100,EventType.OUT),
        ])
]

fundamental_scenerio_list = gr_1_scenarios + gr_2_scenarios + gr_3_scenarios