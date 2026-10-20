import structlog

from dms.domain.temperatures import (
    SensorErrorEnded,
    SensorErrorStarted,
    SensorStale,
    SensorStaleEnded,
    TemperatureNotice,
    UnknownSensorGone,
    UnknownSensorSeen,
)
from dms.logs import events
from dms.units import NS_PER_S

logger = structlog.get_logger()


def log_temperature_notice(notice: TemperatureNotice) -> None:
    match notice:
        case SensorErrorStarted():
            fields = {"sensor_id": notice.sensor_id, "error": notice.error}
            if notice.error_code is not None:
                fields["error_code"] = notice.error_code
            logger.warning(events.TEMPERATURE_SENSOR_ERROR, **fields)
        case SensorErrorEnded():
            logger.info(
                events.TEMPERATURE_SENSOR_ERROR_ENDED,
                sensor_id=notice.sensor_id,
                duration_s=notice.duration_ns / NS_PER_S,
            )
        case SensorStale():
            logger.warning(events.TEMPERATURE_STALE, sensor_id=notice.sensor_id)
        case SensorStaleEnded():
            logger.info(
                events.TEMPERATURE_STALE_ENDED,
                sensor_id=notice.sensor_id,
                duration_s=notice.duration_ns / NS_PER_S,
            )
        case UnknownSensorSeen():
            logger.warning(events.TEMPERATURE_UNKNOWN_SENSOR, address=notice.address)
        case UnknownSensorGone():
            logger.info(events.TEMPERATURE_UNKNOWN_SENSOR_GONE, address=notice.address)
