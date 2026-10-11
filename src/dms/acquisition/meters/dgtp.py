import re
from decimal import Decimal

STATUS_STABLE = "ST"
STATUS_UNSTABLE = "US"
VALID_STATUSES = frozenset({STATUS_STABLE, STATUS_UNSTABLE})
UNIT_KG = "kg"
WEIGHT_FIELD_WIDTH = 8
FIELD_SEPARATOR = ","
FRAME_TERMINATOR = b"\r\n"
FIELD_COUNT = 3
WEIGHT_FIELD_PATTERN = re.compile(r"^ *[+-]?(\d+\.?\d*|\.\d+)$")


def parse_dgtp_frame(frame: bytes) -> int | None:
    try:
        text = frame.decode("ascii")
    except UnicodeDecodeError:
        return None
    fields = text.split(FIELD_SEPARATOR)
    if len(fields) != FIELD_COUNT:
        return None
    status, weight, unit = fields
    if status not in VALID_STATUSES or unit != UNIT_KG:
        return None
    if len(weight) != WEIGHT_FIELD_WIDTH or WEIGHT_FIELD_PATTERN.match(weight) is None:
        return None
    return round(Decimal(weight.strip()))


def encode_dgtp_frame(value_kg: int, stable: bool = True) -> bytes:
    weight = str(value_kg)
    if len(weight) > WEIGHT_FIELD_WIDTH:
        raise ValueError(f"{value_kg} does not fit in {WEIGHT_FIELD_WIDTH} characters")
    status = STATUS_STABLE if stable else STATUS_UNSTABLE
    fields = [status, weight.rjust(WEIGHT_FIELD_WIDTH), UNIT_KG]
    return FIELD_SEPARATOR.join(fields).encode("ascii") + FRAME_TERMINATOR
