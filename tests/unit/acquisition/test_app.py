import threading
from collections.abc import Iterator, MutableMapping
from typing import Any, cast

import pytest
from structlog.testing import capture_logs

from dms.acquisition import app as app_module
from dms.acquisition.app import AcquisitionApp
from dms.acquisition.engine import Engine
from dms.acquisition.ticker import TickTimer
from dms.logs import events
from dms.persistence.writer import PostgresRecordStore, Writer

RUN_ID = 7


class FinishedThreadTarget:
    def run(self) -> None:
        return None


class FakeWriter(FinishedThreadTarget):
    def __init__(self, flushed: bool) -> None:
        self.flushed = flushed


class FakeStore:
    connection = object()


@pytest.fixture
def stopped_runs(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    monkeypatch.setattr(app_module, "stop_run", lambda _connection, run_id: calls.append(run_id))
    return calls


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured


def build(writer_flushed: bool = True) -> AcquisitionApp:
    acquisition = AcquisitionApp(
        adapters=[],
        timer=cast(TickTimer, FinishedThreadTarget()),
        engine=cast(Engine, FinishedThreadTarget()),
        writer=cast(Writer, FakeWriter(writer_flushed)),
        store=cast(PostgresRecordStore, FakeStore()),
        run_id=RUN_ID,
        producers_stop=threading.Event(),
        engine_stop=threading.Event(),
        writer_stop=threading.Event(),
    )
    acquisition.start()
    return acquisition


def test_clean_stop_closes_the_run(stopped_runs: list[int]) -> None:
    acquisition = build()

    acquisition.stop()

    assert stopped_runs == [RUN_ID]
    assert not acquisition.failed


def test_lost_records_leave_the_run_open(
    stopped_runs: list[int], logs: list[MutableMapping[str, Any]]
) -> None:
    acquisition = build(writer_flushed=False)

    acquisition.stop()

    assert stopped_runs == []
    assert acquisition.failed
    assert [entry["event"] for entry in logs] == [events.SERVICE_STOP_INCOMPLETE]


def test_crashed_thread_leaves_the_run_open(stopped_runs: list[int]) -> None:
    acquisition = build()
    acquisition.fail()

    acquisition.stop()

    assert stopped_runs == []
    assert acquisition.failed


def test_wait_returns_after_shutdown_request() -> None:
    acquisition = build()
    threading.Timer(0.01, acquisition.request_shutdown).start()

    acquisition.wait()
