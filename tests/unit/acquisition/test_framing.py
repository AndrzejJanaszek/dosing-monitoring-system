from dms.acquisition.serial.framing import Framer

CRLF = b"\r\n"
MAX_FRAME_LENGTH = 64


def test_complete_frames_are_split_at_the_terminator() -> None:
    framer = Framer(b"", CRLF, MAX_FRAME_LENGTH)

    assert framer.feed(b"one\r\ntwo\r\n") == [b"one", b"two"]


def test_frame_split_across_chunks_is_joined() -> None:
    framer = Framer(b"", CRLF, MAX_FRAME_LENGTH)

    assert framer.feed(b"ST,   ") == []
    assert framer.feed(b"  66,kg\r") == []
    assert framer.feed(b"\nUS") == [b"ST,     66,kg"]
    assert framer.feed(b",1\r\n") == [b"US,1"]


def test_incomplete_tail_waits_for_the_next_chunk() -> None:
    framer = Framer(b"", CRLF, MAX_FRAME_LENGTH)

    assert framer.feed(b"a\r\nb") == [b"a"]
    assert framer.feed(b"c\r\n") == [b"bc"]


def test_empty_frame_is_passed_on() -> None:
    assert Framer(b"", CRLF, MAX_FRAME_LENGTH).feed(b"\r\n") == [b""]


def test_start_marker_drops_leading_garbage() -> None:
    framer = Framer(b"\x02", b"\x03", MAX_FRAME_LENGTH)

    assert framer.feed(b"junk\x02abc\x03more\x02de") == [b"abc"]
    assert framer.feed(b"f\x03") == [b"def"]


def test_start_marker_can_be_split_across_chunks() -> None:
    framer = Framer(b"<<", b">", MAX_FRAME_LENGTH)

    assert framer.feed(b"x<") == []
    assert framer.feed(b"<abc>") == [b"abc"]


def test_overlong_frame_without_terminator_clears_buffer_and_counts() -> None:
    framer = Framer(b"", CRLF, max_frame_length=8)

    assert framer.feed(b"x" * 20) == []
    assert framer.rejected_count == 1
    assert framer.feed(b"ok\r\n") == [b"ok"]


def test_overlong_frame_with_terminator_is_rejected() -> None:
    framer = Framer(b"", CRLF, max_frame_length=8)

    assert framer.feed(b"x" * 20 + b"\r\nok\r\n") == [b"ok"]
    assert framer.rejected_count == 1


def test_reset_discards_partial_frame() -> None:
    framer = Framer(b"", CRLF, MAX_FRAME_LENGTH)
    framer.feed(b"partial")

    framer.reset()

    assert framer.feed(b"new\r\n") == [b"new"]
