from scenario import Scenario
from header import *


# -10k, -10k, +40k, -10k
# 
# expected results:
# clear     -10k
# clear     -10k
# collision +30k    | real +40k
# collision +0k     | real -10k

s1 = Scenario(
        "out 10k, out 10k, in 40k, COL out 10k", 
        [
            Event(0,10,-1000,EventType.OUT),
            Event(20,30,-1000,EventType.OUT),
            Event(40,80,1000,EventType.IN),
            Event(50,60,-1000,EventType.OUT),
         ]
        )