import argparse
import signal
import threading
from collections.abc import Sequence
from pathlib import Path

from dms.simulator.meter import MeterSimulator

DEFAULT_RATE_HZ = 10.0
DEFAULT_START_KG = 1000
DEFAULT_STEP_KG = 20
SHUTDOWN_POLL_S = 0.5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dms-simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    meter = commands.add_parser("meter", help="simulate a DGTP meter on a pseudo-terminal")
    meter.add_argument("--rate", type=float, default=DEFAULT_RATE_HZ, help="frames per second")
    meter.add_argument("--start", type=int, default=DEFAULT_START_KG, help="lowest value in kg")
    meter.add_argument("--step", type=int, default=DEFAULT_STEP_KG, help="increase per frame in kg")
    meter.add_argument("--link", type=Path, help="symbolic link to create for the port")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    simulator = MeterSimulator(arguments.rate, arguments.start, arguments.step, arguments.link)
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    print(arguments.link if arguments.link is not None else simulator.port_path, flush=True)
    simulator.start()
    while not stop_event.wait(SHUTDOWN_POLL_S):
        pass
    simulator.stop()
    return 0
