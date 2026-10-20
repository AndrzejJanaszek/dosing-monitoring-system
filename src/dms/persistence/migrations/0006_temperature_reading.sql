-- schema-change: minor

CREATE TYPE dms.temperature_error AS ENUM (
    'read_failed',
    'power_reset',
    'insufficient_power',
    'out_of_range',
    'unrecognized'
);

CREATE TABLE dms.temperature_reading (
    sensor_id smallint NOT NULL REFERENCES dms.temperature_sensor,
    t timestamptz NOT NULL,
    value_c numeric(5, 2),
    error dms.temperature_error,
    PRIMARY KEY (sensor_id, t),
    CHECK ((error IS NULL OR error = 'out_of_range') = (value_c IS NOT NULL))
);

CREATE TABLE dms.unknown_sensor_reading (
    address text NOT NULL CHECK (address ~ '^[0-9A-F]{16}$'),
    t timestamptz NOT NULL,
    value_c numeric(5, 2),
    error dms.temperature_error,
    PRIMARY KEY (address, t),
    CHECK ((error IS NULL OR error = 'out_of_range') = (value_c IS NOT NULL))
);

GRANT INSERT ON dms.temperature_reading TO dms_writer;
GRANT INSERT ON dms.unknown_sensor_reading TO dms_writer;
