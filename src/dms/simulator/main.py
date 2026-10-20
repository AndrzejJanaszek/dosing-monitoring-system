import argparse
import signal
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from dms.exit_codes import EXIT_CONFIG_ERROR, EXIT_OK
from dms.simulator.catalog import SCENARIOS
from dms.simulator.dms_config import acquisition_config, render_acquisition_toml
from dms.simulator.scenario import Scenario
from dms.simulator.transport import SimulationRunner
from dms.units import NS_PER_S


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dms-simulator")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list the scenarios")
    run = commands.add_parser("run", help="run a scenario on pseudo-terminals")
    run.add_argument("scenario")
    run.add_argument("--link-dir", type=Path, required=True, help="directory for port links")
    run.add_argument("--wait", action="store_true", help="start the scenario after Enter")
    config = commands.add_parser("config", help="print the matching acquisition.toml")
    config.add_argument("scenario")
    config.add_argument("--link-dir", type=Path, required=True, help="directory for port links")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "list":
        return _list_scenarios()
    scenario = SCENARIOS.get(arguments.scenario)
    if scenario is None:
        print(
            f"unknown scenario '{arguments.scenario}', available: {', '.join(SCENARIOS)}",
            file=sys.stderr,
        )
        return EXIT_CONFIG_ERROR
    if arguments.command == "config":
        return _print_config(scenario, arguments.link_dir)
    return _run_scenario(scenario, arguments.link_dir, wait_for_enter=arguments.wait)


def _list_scenarios() -> int:
    for scenario in SCENARIOS.values():
        silos = len(scenario.layout.silos)
        tanks = sum(len(silo.tanks) for silo in scenario.layout.silos)
        duration_s = scenario.duration_ns / NS_PER_S
        print(f"{scenario.name}\tsilos={silos} tanks={tanks}\t{duration_s:g} s")
    return EXIT_OK


def _print_config(scenario: Scenario, link_dir: Path) -> int:
    print(render_acquisition_toml(acquisition_config(scenario.layout, link_dir)), end="")
    return EXIT_OK


def _run_scenario(scenario: Scenario, link_dir: Path, *, wait_for_enter: bool) -> int:
    runner = SimulationRunner(scenario, link_dir)
    runner.open()
    for device_id, port in runner.ports.items():
        print(f"{device_id} -> {link_dir / device_id} -> {port.path}", flush=True)

    signal.signal(signal.SIGINT, lambda *_: runner.stop())
    signal.signal(signal.SIGTERM, lambda *_: runner.stop())
    threading.Thread(target=_announce_finish, args=(runner,), daemon=True).start()

    if wait_for_enter:
        threading.Thread(target=_start_on_enter, args=(runner,), daemon=True).start()
        print("press Enter to start the scenario", flush=True)
    else:
        _start(runner)

    runner.run()
    return EXIT_OK


def _start(runner: SimulationRunner) -> None:
    runner.start_scenario()
    print("scenario started", flush=True)


def _start_on_enter(runner: SimulationRunner) -> None:
    if sys.stdin.readline():
        _start(runner)
    else:
        print("stdin closed, the scenario was not started", flush=True)


def _announce_finish(runner: SimulationRunner) -> None:
    runner.scenario_finished.wait()
    print("scenario finished, holding final state", flush=True)
