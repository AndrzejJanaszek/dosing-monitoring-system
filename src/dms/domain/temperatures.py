from enum import StrEnum


class TemperatureError(StrEnum):
    READ_FAILED = "read_failed"
    POWER_RESET = "power_reset"
    INSUFFICIENT_POWER = "insufficient_power"
    OUT_OF_RANGE = "out_of_range"
    UNRECOGNIZED = "unrecognized"
