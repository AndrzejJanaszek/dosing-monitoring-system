import pytest

from dms.acquisition.meters.dgtp import encode_dgtp_frame, parse_dgtp_frame
from dms.acquisition.meters.parsing import OutOfRange


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (b"ST,      66,kg", 66),
        (b"ST,     -40,kg", -40),
        (b"US,    1020,kg", 1020),
        (b"ST,       0,kg", 0),
        (b"ST,    12.4,kg", 12),
        (b"ST,    12.6,kg", 13),
        (b"ST,   -12.6,kg", -13),
        (b"ST,   +100.,kg", 100),
        (b"ST,12345678,kg", 12345678),
        (b"ST,-1234567,kg", -1234567),
    ],
)
def test_valid_frame_gives_rounded_kilograms(frame: bytes, expected: int) -> None:
    assert parse_dgtp_frame(frame) == expected


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (b"OL,      66,kg", OutOfRange.OVERLOAD),
        (b"UL,        ,kg", OutOfRange.UNDERLOAD),
        (b"OL,--------,kg", OutOfRange.OVERLOAD),
    ],
)
def test_overload_and_underload_are_recognised(frame: bytes, expected: OutOfRange) -> None:
    assert parse_dgtp_frame(frame) is expected


@pytest.mark.parametrize(
    "frame",
    [
        b"",
        b"garbage",
        b"ST,      66,lb",
        b"ST,      66,KG",
        b"OL,      66,lb",
        b"XX,      66,kg",
        b"ST,     66,kg",
        b"ST,       66,kg",
        b"ST,      6x,kg",
        b"ST,       -,kg",
        b"ST,    - 40,kg",
        b"ST,        ,kg",
        b"ST,      66",
        b"ST,      66,kg,extra",
        b"GS,ST,      66,kg",
        b"ST,\xff\xfe      ,kg",
        b"ST,      66,kg\r",
    ],
)
def test_invalid_frame_is_rejected_without_exception(frame: bytes) -> None:
    assert parse_dgtp_frame(frame) is None


def test_parser_and_encoder_agree_over_value_range() -> None:
    for value in range(-9999, 100_000, 7):
        for stable in (True, False):
            encoded = encode_dgtp_frame(value, stable)

            assert encoded.endswith(b"\r\n")
            assert parse_dgtp_frame(encoded.removesuffix(b"\r\n")) == value


def test_encoder_sets_status_and_pads_to_eight_characters() -> None:
    assert encode_dgtp_frame(66) == b"ST,      66,kg\r\n"
    assert encode_dgtp_frame(-40, stable=False) == b"US,     -40,kg\r\n"


@pytest.mark.parametrize("value", [123456789, -12345678])
def test_encoder_rejects_value_that_does_not_fit(value: int) -> None:
    with pytest.raises(ValueError, match="does not fit"):
        encode_dgtp_frame(value)
