-- schema-change: minor

CREATE TABLE dms.temperature_sensor (
    id smallint PRIMARY KEY,
    silo_id smallint REFERENCES dms.silo,
    leg smallint,
    name text NOT NULL,
    active boolean NOT NULL,
    CHECK (leg IS NULL OR (silo_id IS NOT NULL AND leg >= 1))
);

GRANT SELECT, INSERT, UPDATE ON dms.temperature_sensor TO dms_writer;
