from collections.abc import Mapping
from dataclasses import dataclass, field

from dms.domain.records import TemperatureRecord, UnknownSensorRecord
from dms.domain.temperature_error import TemperatureError
from dms.messages import TemperatureEntry, TemperatureReadings, Tick

ERRORS_REPORTED_BY_BOARD = {
    error.value: error
    for error in (
        TemperatureError.READ_FAILED,
        TemperatureError.POWER_RESET,
        TemperatureError.INSUFFICIENT_POWER,
    )
}


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorErrorStarted:
    sensor_id: int
    error: TemperatureError
    error_code: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorErrorEnded:
    sensor_id: int
    duration_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorStale:
    sensor_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SensorStaleEnded:
    sensor_id: int
    duration_ns: int


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownSensorSeen:
    address: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownSensorGone:
    address: str


type TemperatureNotice = (
    SensorErrorStarted
    | SensorErrorEnded
    | SensorStale
    | SensorStaleEnded
    | UnknownSensorSeen
    | UnknownSensorGone
)
type TemperatureOutput = TemperatureRecord | UnknownSensorRecord | TemperatureNotice


class TemperatureSensors:
    def __init__(
        self,
        *,
        sensor_id_by_address: Mapping[str, int],
        record_interval_ns: int,
        max_reading_age_ns: int,
        tick_interval_ns: int,
        min_valid_c: float,
        max_valid_c: float,
        started_mono_ns: int,
    ) -> None:
        self._sensor_id_by_address = dict(sensor_id_by_address)
        self._record_interval_ns = record_interval_ns
        self._max_reading_age_ns = max_reading_age_ns
        self._tick_interval_ns = tick_interval_ns
        self._min_valid_c = min_valid_c
        self._max_valid_c = max_valid_c
        self._sensors = {
            sensor_id: _Source(started_mono_ns=started_mono_ns)
            for sensor_id in self._sensor_id_by_address.values()
        }
        self._unknown: dict[str, _Source] = {}

    def on_readings(self, readings: TemperatureReadings) -> list[TemperatureNotice]:
        notices: list[TemperatureNotice] = []
        for entry in readings.entries:
            result = self._result_of(entry, readings)
            sensor_id = self._sensor_id_by_address.get(entry.address)
            if sensor_id is not None:
                notices.extend(self._receive(sensor_id, self._sensors[sensor_id], result))
            else:
                notices.extend(self._receive_unknown(entry.address, result))
        return notices

    def on_tick(self, tick: Tick) -> list[TemperatureOutput]:
        outputs: list[TemperatureOutput] = []
        for sensor_id, source in self._sensors.items():
            outputs.extend(self._tick_sensor(sensor_id, source, tick))
        for address, source in list(self._unknown.items()):
            outputs.extend(self._tick_unknown(address, source, tick))
        return outputs

    def _result_of(self, entry: TemperatureEntry, readings: TemperatureReadings) -> _Result:
        error: TemperatureError | None = None
        error_code: str | None = None
        if entry.error_code is not None:
            error = ERRORS_REPORTED_BY_BOARD.get(entry.error_code, TemperatureError.UNRECOGNIZED)
            error_code = entry.error_code if error is TemperatureError.UNRECOGNIZED else None
        elif entry.value_c is not None and not (
            self._min_valid_c <= entry.value_c <= self._max_valid_c
        ):
            error = TemperatureError.OUT_OF_RANGE
        return _Result(
            wall_ns=readings.wall_ns,
            mono_ns=readings.mono_ns,
            value_c=entry.value_c,
            error=error,
            error_code=error_code,
        )

    def _receive(
        self, sensor_id: int, source: _Source, result: _Result
    ) -> list[TemperatureNotice]:
        notices: list[TemperatureNotice] = []
        if source.stale_since_mono_ns is not None:
            notices.append(
                SensorStaleEnded(
                    sensor_id=sensor_id, duration_ns=result.mono_ns - source.stale_since_mono_ns
                )
            )
            source.stale_since_mono_ns = None

        if result.error is not None and source.error_since_mono_ns is None:
            source.error_since_mono_ns = result.mono_ns
            notices.append(
                SensorErrorStarted(
                    sensor_id=sensor_id, error=result.error, error_code=result.error_code
                )
            )
            if result.error_code is not None:
                source.reported_error_codes.add(result.error_code)
        elif (
            result.error is not None
            and result.error_code is not None
            and result.error_code not in source.reported_error_codes
        ):
            source.reported_error_codes.add(result.error_code)
            notices.append(
                SensorErrorStarted(
                    sensor_id=sensor_id, error=result.error, error_code=result.error_code
                )
            )
        elif result.error is None and source.error_since_mono_ns is not None:
            notices.append(
                SensorErrorEnded(
                    sensor_id=sensor_id, duration_ns=result.mono_ns - source.error_since_mono_ns
                )
            )
            source.error_since_mono_ns = None
            source.reported_error_codes.clear()

        source.last = result
        return notices

    def _receive_unknown(self, address: str, result: _Result) -> list[TemperatureNotice]:
        notices: list[TemperatureNotice] = []
        source = self._unknown.get(address)
        if source is None:
            source = _Source(started_mono_ns=result.mono_ns)
            self._unknown[address] = source
            notices.append(UnknownSensorSeen(address=address))
        source.last = result
        return notices

    def _tick_sensor(self, sensor_id: int, source: _Source, tick: Tick) -> list[TemperatureOutput]:
        if self._is_stale(source, tick):
            if source.stale_since_mono_ns is not None:
                return []
            source.stale_since_mono_ns = self._reference_mono_ns(source) + self._max_reading_age_ns
            return [SensorStale(sensor_id=sensor_id)]

        result = self._due_result(source, tick)
        if result is None:
            return []
        return [
            TemperatureRecord(
                sensor_id=sensor_id,
                wall_ns=result.wall_ns,
                value_c=result.value_c,
                error=result.error,
            )
        ]

    def _tick_unknown(self, address: str, source: _Source, tick: Tick) -> list[TemperatureOutput]:
        if self._is_stale(source, tick):
            del self._unknown[address]
            return [UnknownSensorGone(address=address)]

        result = self._due_result(source, tick)
        if result is None:
            return []
        return [
            UnknownSensorRecord(
                address=address,
                wall_ns=result.wall_ns,
                value_c=result.value_c,
                error=result.error,
            )
        ]

    def _reference_mono_ns(self, source: _Source) -> int:
        return source.last.mono_ns if source.last is not None else source.started_mono_ns

    def _is_stale(self, source: _Source, tick: Tick) -> bool:
        return tick.mono_ns - self._reference_mono_ns(source) > self._max_reading_age_ns

    def _due_result(self, source: _Source, tick: Tick) -> _Result | None:
        result = source.last
        if result is None or result.mono_ns == source.recorded_mono_ns:
            return None
        last_tick_ns = source.last_record_tick_mono_ns
        if (
            last_tick_ns is not None
            and tick.mono_ns - last_tick_ns
            < self._record_interval_ns - self._tick_interval_ns // 2
        ):
            return None
        source.recorded_mono_ns = result.mono_ns
        source.last_record_tick_mono_ns = tick.mono_ns
        return result


@dataclass(frozen=True, slots=True, kw_only=True)
class _Result:
    wall_ns: int
    mono_ns: int
    value_c: float | None
    error: TemperatureError | None
    error_code: str | None


@dataclass(slots=True, kw_only=True)
class _Source:
    started_mono_ns: int
    last: _Result | None = None
    recorded_mono_ns: int | None = None
    last_record_tick_mono_ns: int | None = None
    stale_since_mono_ns: int | None = None
    error_since_mono_ns: int | None = None
    reported_error_codes: set[str] = field(default_factory=set)
