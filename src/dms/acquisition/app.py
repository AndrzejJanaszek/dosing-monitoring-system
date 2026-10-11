import queue
import threading
import time
from collections.abc import Callable

import psycopg
import serial
import structlog
from psycopg.rows import TupleRow

from dms.acquisition.clock import Clock
from dms.acquisition.engine import Engine
from dms.acquisition.meters.adapter import MeterAdapter, SerialPort
from dms.acquisition.meters.dgtp import parse_dgtp_frame
from dms.acquisition.meters.framing import Framer
from dms.acquisition.ticker import TickTimer
from dms.config.models import AcquisitionConfig, MeterConfig
from dms.domain.records import MeterRecord
from dms.domain.silo import Silo
from dms.logs import events
from dms.messages import EngineMessage
from dms.persistence.catalog import stop_run
from dms.persistence.writer import PostgresRecordStore, Writer

PORT_READ_TIMEOUT_S = 0.1
SHUTDOWN_JOIN_TIMEOUT_S = 10.0
SHUTDOWN_POLL_S = 0.2
NS_PER_S = 1_000_000_000
FRAME_PARSERS = {"dgtp": parse_dgtp_frame}


def serial_port_opener(meter: MeterConfig) -> Callable[[], SerialPort]:
    def open_port() -> SerialPort:
        return serial.Serial(meter.port, meter.baudrate, timeout=PORT_READ_TIMEOUT_S)

    return open_port


class AcquisitionApp:
    def __init__(
        self,
        *,
        adapters: list[MeterAdapter],
        timer: TickTimer,
        engine: Engine,
        writer: Writer,
        store: PostgresRecordStore,
        run_id: int,
        producers_stop: threading.Event,
        engine_stop: threading.Event,
        writer_stop: threading.Event,
    ) -> None:
        self._adapter_threads = [
            threading.Thread(target=adapter.run, name=f"adapter-{index}", daemon=True)
            for index, adapter in enumerate(adapters)
        ]
        self._timer_thread = threading.Thread(target=timer.run, name="timer", daemon=True)
        self._engine_thread = threading.Thread(target=engine.run, name="engine", daemon=True)
        self._writer_thread = threading.Thread(target=writer.run, name="writer", daemon=True)
        self._store = store
        self._run_id = run_id
        self._producers_stop = producers_stop
        self._engine_stop = engine_stop
        self._writer_stop = writer_stop
        self._shutdown_requested = False
        self.failed = False

    def start(self) -> None:
        self._writer_thread.start()
        self._engine_thread.start()
        self._timer_thread.start()
        for thread in self._adapter_threads:
            thread.start()

    def request_shutdown(self) -> None:
        self._shutdown_requested = True

    def fail(self) -> None:
        self.failed = True
        self.request_shutdown()

    def wait(self) -> None:
        while not self._shutdown_requested:
            time.sleep(SHUTDOWN_POLL_S)

    def stop(self) -> None:
        self._producers_stop.set()
        for thread in [*self._adapter_threads, self._timer_thread]:
            thread.join(SHUTDOWN_JOIN_TIMEOUT_S)
        self._engine_stop.set()
        self._engine_thread.join(SHUTDOWN_JOIN_TIMEOUT_S)
        self._writer_stop.set()
        self._writer_thread.join(SHUTDOWN_JOIN_TIMEOUT_S)
        try:
            stop_run(self._store.connection, self._run_id)
        except psycopg.Error as error:
            structlog.get_logger().warning(
                events.DB_WRITE_ERROR, error=str(error), context="stop_run"
            )


def build_acquisition(
    *,
    config: AcquisitionConfig,
    clock: Clock,
    connection: psycopg.Connection[TupleRow],
    reconnect: Callable[[], psycopg.Connection[TupleRow]],
    run_id: int,
) -> AcquisitionApp:
    max_reading_age_ns = round(config.engine.max_reading_age_s * NS_PER_S)
    silos = [Silo(silo.id, max_reading_age_ns) for silo in config.silos]
    silos_by_meter = {
        silo_config.meter: silo for silo_config, silo in zip(config.silos, silos, strict=True)
    }
    engine_queue: queue.Queue[EngineMessage] = queue.Queue()
    record_queue: queue.Queue[MeterRecord] = queue.Queue()
    producers_stop = threading.Event()
    engine_stop = threading.Event()
    writer_stop = threading.Event()
    adapters = [
        MeterAdapter(
            meter_id=meter.id,
            port_name=meter.port,
            port_opener=serial_port_opener(meter),
            framer=Framer(meter.frame_start.encode(), meter.frame_end.encode()),
            parser=FRAME_PARSERS[meter.format],
            clock=clock,
            out_queue=engine_queue,
            stop_event=producers_stop,
            reconnect_delay_s=meter.reconnect_delay_s,
            silence_timeout_s=meter.silence_timeout_s,
        )
        for meter in config.meters
    ]
    store = PostgresRecordStore(connection, reconnect)
    return AcquisitionApp(
        adapters=adapters,
        timer=TickTimer(
            clock=clock,
            interval_ns=round(config.engine.tick_interval_s * NS_PER_S),
            out_queue=engine_queue,
            stop_event=producers_stop,
        ),
        engine=Engine(
            in_queue=engine_queue,
            out_queue=record_queue,
            silos_by_meter=silos_by_meter,
            silos=silos,
            stop_event=engine_stop,
        ),
        writer=Writer(in_queue=record_queue, store=store, stop_event=writer_stop),
        store=store,
        run_id=run_id,
        producers_stop=producers_stop,
        engine_stop=engine_stop,
        writer_stop=writer_stop,
    )
