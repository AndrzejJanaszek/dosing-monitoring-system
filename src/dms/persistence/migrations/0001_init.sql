-- schema-change: major

ALTER DEFAULT PRIVILEGES FOR ROLE dms_owner IN SCHEMA dms GRANT SELECT ON TABLES TO dms_read;

CREATE TABLE dms.silo (
    id smallint PRIMARY KEY,
    name text NOT NULL,
    active boolean NOT NULL
);

CREATE TABLE dms.run (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL,
    stopped_at timestamptz,
    app_version text NOT NULL,
    config jsonb NOT NULL
);

CREATE TABLE dms.meter_reading (
    silo_id smallint NOT NULL REFERENCES dms.silo,
    t timestamptz NOT NULL,
    value_kg integer NOT NULL,
    PRIMARY KEY (silo_id, t)
);

GRANT SELECT, INSERT, UPDATE ON dms.silo TO dms_writer;
GRANT SELECT, INSERT, UPDATE ON dms.run TO dms_writer;
GRANT INSERT ON dms.meter_reading TO dms_writer;
