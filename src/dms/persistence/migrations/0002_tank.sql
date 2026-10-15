-- schema-change: minor

CREATE TABLE dms.tank (
    id smallint PRIMARY KEY,
    silo_id smallint NOT NULL REFERENCES dms.silo,
    name text NOT NULL,
    active boolean NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON dms.tank TO dms_writer;
