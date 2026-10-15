import queue
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from functools import partial

import psycopg
import serial
import structlog
from psycopg.rows import TupleRow

from dms.acquisition.arduino.handler import ArduinoFrameHandler
from dms.acquisition.arduino.mapping import SignalMapper
from dms.acquisition.clock import NS_PER_S, Clock
from dms.acquisition.engine import Engine
from dms.acquisition.meters.dgtp import parse_dgtp_frame
from dms.acquisition.meters.handler import MeterFrameHandler
from dms.acquisition.meters.parsing import FrameParser
from dms.acquisition.serial.adapter import SerialAdapter
from dms.acquisition.serial.framing import Framer
from dms.acquisition.ticker import TickTimer
from dms.config.models import AcquisitionConfig, MeterFormat
from dms.domain.records import WriterRecord
from dms.domain.silo import Silo
from dms.logs import events
from dms.messages import EngineMessage
from dms.persistence.catalog import stop_run
from dms.persistence.writer import PostgresRecordStore, Writer

PORT_READ_TIMEOUT_S = 0.1
SHUTDOWN_JOIN_TIMEOUT_S = 10.0
SHUTDOWN_POLL_S = 0.2
READING_CACHE_WINDOW_S = 60
METER_PARSERS: Mapping[MeterFormat, FrameParser] = {"dgtp": parse_dgtp_frame}


class AcquisitionApp:
    def __init__(
        self,
        *,
        adapters: list[SerialAdapter],
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
        self._writer = writer
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
        if not self._stopped_cleanly():
            self.failed = True
            structlog.get_logger().error(events.SERVICE_STOP_INCOMPLETE, run_id=self._run_id)
            return
        try:
            stop_run(self._store.connection, self._run_id)
        except psycopg.Error as error:
            self.failed = True
            structlog.get_logger().warning(
                events.DB_WRITE_ERROR, error=str(error), context="stop_run"
            )

    def _stopped_cleanly(self) -> bool:
        threads = [
            *self._adapter_threads,
            self._timer_thread,
            self._engine_thread,
            self._writer_thread,
        ]
        return (
            not self.failed
            and self._writer.flushed
            and not any(thread.is_alive() for thread in threads)
        )


def build_silos(
    config: AcquisitionConfig,
    *,
    new_event_id: Callable[[], uuid.UUID],
    started_wall_ns: int,
    started_mono_ns: int,
) -> dict[str, Silo]:
    return {
        silo.meter_id: Silo(
            silo.id,
            max_reading_age_ns=round(config.engine.max_reading_age_s * NS_PER_S),
            max_signal_age_ns=round(config.engine.max_signal_age_s * NS_PER_S),
            reading_cache_window_ns=READING_CACHE_WINDOW_S * NS_PER_S,
            tank_ids=tuple(tank.id for tank in config.tanks if tank.silo_id == silo.id),
            new_event_id=new_event_id,
            started_wall_ns=started_wall_ns,
            started_mono_ns=started_mono_ns,
        )
        for silo in config.silos
    }


def build_acquisition(
    *,
    config: AcquisitionConfig,
    clock: Clock,
    connection: psycopg.Connection[TupleRow],
    reconnect: Callable[[], psycopg.Connection[TupleRow]],
    run_id: int,
) -> AcquisitionApp:
    silos_by_meter = build_silos(
        config,
        new_event_id=uuid.uuid7,
        started_wall_ns=clock.wall_ns(),
        started_mono_ns=clock.mono_ns(),
    )
    engine_queue: queue.Queue[EngineMessage] = queue.Queue()
    record_queue: queue.Queue[WriterRecord] = queue.Queue()
    producers_stop = threading.Event()
    engine_stop = threading.Event()
    writer_stop = threading.Event()
    adapters = [
        SerialAdapter(
            device_id=meter.id,
            port_name=meter.port,
            port_opener=partial(
                serial.Serial, meter.port, meter.baudrate, timeout=PORT_READ_TIMEOUT_S
            ),
            framer=Framer(
                meter.frame_start.encode(), meter.frame_end.encode(), meter.max_frame_length
            ),
            handler=MeterFrameHandler(
                meter_id=meter.id,
                port_name=meter.port,
                parser=METER_PARSERS[meter.format],
                out_queue=engine_queue,
            ),
            clock=clock,
            stop_event=producers_stop,
            reconnect_delay_s=meter.reconnect_delay_s,
            silence_timeout_s=meter.silence_timeout_s,
        )
        for meter in config.meters
    ]
    board = config.board
    if board is not None:
        adapters.append(
            SerialAdapter(
                device_id=board.id,
                port_name=board.port,
                port_opener=partial(
                    serial.Serial, board.port, board.baudrate, timeout=PORT_READ_TIMEOUT_S
                ),
                framer=Framer(
                    board.frame_start.encode(), board.frame_end.encode(), board.max_frame_length
                ),
                handler=ArduinoFrameHandler(
                    board_id=board.id,
                    port_name=board.port,
                    mapper=SignalMapper(config.tanks),
                    out_queue=engine_queue,
                ),
                clock=clock,
                stop_event=producers_stop,
                reconnect_delay_s=board.reconnect_delay_s,
                silence_timeout_s=board.silence_timeout_s,
            )
        )
    store = PostgresRecordStore(connection, reconnect, run_id)
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
            stop_event=engine_stop,
        ),
        writer=Writer(in_queue=record_queue, store=store, stop_event=writer_stop),
        store=store,
        run_id=run_id,
        producers_stop=producers_stop,
        engine_stop=engine_stop,
        writer_stop=writer_stop,
    )
