from typing import Dict, Optional

from parsers.parsers import parse_signal_json
from event_change_handler.event_change_handler import EventChangeHandler

class EventDetector:
    def __init__(self, change_handler: EventChangeHandler):

        self.change_handler = change_handler

        # previous snapshot
        self.prev_data: Dict[int, int] = {}

    # data -> raw json string
    # format:
    # {
    #   "0": 1,
    #   "1": 0
    # }
    def notify(self, data: str):

        # parse raw json
        parsed_data: Dict[int, int] = parse_signal_json(data)

        # first snapshot initialization
        if not self.prev_data:
            self.prev_data = parsed_data.copy()
            return

        # detect changes
        for pin, value in parsed_data.items():

            prev_value: Optional[int] = self.prev_data.get(pin)

            # state changed
            if prev_value != value:
                print("State change detected")

                self.change_handler.notify(
                    target_status=value,
                    pin=pin
                )

        # update snapshot
        self.prev_data = parsed_data.copy()