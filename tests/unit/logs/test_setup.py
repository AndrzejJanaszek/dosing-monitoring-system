import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from dms.logs.setup import LogFormat, configure_logging


class TerminalStream(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()


@pytest.mark.parametrize("log_format", ["json", "auto"])
def test_json_line_has_event_level_timestamp_and_bound_fields(log_format: LogFormat) -> None:
    stream = io.StringIO()
    configure_logging("INFO", log_format, stream)

    structlog.get_logger().bind(meter_id="m1").info("port.opened", port="/dev/ttyUSB0")

    line = json.loads(stream.getvalue())
    assert line["event"] == "port.opened"
    assert line["level"] == "info"
    assert line["meter_id"] == "m1"
    assert line["port"] == "/dev/ttyUSB0"
    assert line["timestamp"].endswith("Z")


def test_standard_library_logs_pass_through_the_same_renderer() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)

    logging.getLogger("psycopg").warning("pool is slow")

    line = json.loads(stream.getvalue())
    assert line["event"] == "pool is slow"
    assert line["level"] == "warning"
    assert "timestamp" in line


def test_level_filters_lower_severity() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", "json", stream)

    structlog.get_logger().info("service.started")
    structlog.get_logger().warning("port.silence")

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["port.silence"]


def test_exception_is_rendered_into_json() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger().exception("thread.crashed")

    assert "RuntimeError: boom" in json.loads(stream.getvalue())["exception"]


def test_console_format_is_human_readable() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "console", stream)

    structlog.get_logger().info("port.opened", meter_id="m1")

    output = stream.getvalue()
    assert "port.opened" in output
    assert "meter_id" in output
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)


def test_auto_format_uses_console_on_terminal() -> None:
    stream = TerminalStream()
    configure_logging("INFO", "auto", stream)

    structlog.get_logger().info("port.opened")

    with pytest.raises(json.JSONDecodeError):
        json.loads(stream.getvalue())


def test_reconfiguring_does_not_duplicate_output() -> None:
    stream = io.StringIO()
    configure_logging("INFO", "json", stream)
    configure_logging("INFO", "json", stream)

    structlog.get_logger().info("service.started")

    assert len(stream.getvalue().splitlines()) == 1
