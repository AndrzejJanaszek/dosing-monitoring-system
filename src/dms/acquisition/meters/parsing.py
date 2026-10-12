from collections.abc import Callable
from enum import StrEnum


class OutOfRange(StrEnum):
    OVERLOAD = "OL"
    UNDERLOAD = "UL"


type FrameParser = Callable[[bytes], int | OutOfRange | None]
