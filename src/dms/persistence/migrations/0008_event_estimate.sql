-- schema-change: minor

CREATE TABLE dms.event_estimate (
    event_id uuid NOT NULL REFERENCES dms.tank_event,
    method text NOT NULL,
    params jsonb NOT NULL,
    value_kg integer,
    missing_reason text,
    computed_at timestamptz NOT NULL,
    PRIMARY KEY (event_id, method, params),
    CONSTRAINT event_estimate_value_or_missing_reason
        CHECK ((value_kg IS NULL) <> (missing_reason IS NULL))
);

GRANT SELECT, INSERT, UPDATE ON dms.event_estimate TO dms_writer;
