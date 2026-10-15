-- schema-change: minor

CREATE TYPE dms.event_type AS ENUM ('dispense', 'refill');

CREATE TYPE dms.event_origin AS ENUM ('signal');

CREATE TYPE dms.event_status AS ENUM ('in_progress', 'completed', 'incomplete');

CREATE TYPE dms.start_quality AS ENUM ('fresh', 'stale_reading', 'unknown');

CREATE TYPE dms.end_quality AS ENUM (
    'fresh',
    'stale_reading',
    'signal_lost',
    'service_stopped',
    'service_crashed'
);

CREATE TABLE dms.tank_event (
    id uuid PRIMARY KEY,
    tank_id smallint NOT NULL REFERENCES dms.tank,
    run_id integer NOT NULL REFERENCES dms.run,
    type dms.event_type NOT NULL,
    origin dms.event_origin NOT NULL,
    status dms.event_status NOT NULL,
    start_at timestamptz NOT NULL,
    start_value_kg integer,
    start_quality dms.start_quality NOT NULL,
    end_at timestamptz,
    end_value_kg integer,
    end_quality dms.end_quality,
    duration_ms integer,
    CONSTRAINT tank_event_end_matches_status
        CHECK ((status = 'in_progress') = (end_at IS NULL)),
    CONSTRAINT tank_event_end_quality_matches_status
        CHECK ((status = 'in_progress') = (end_quality IS NULL)),
    CONSTRAINT tank_event_completed_matches_qualities
        CHECK (
            status = 'in_progress'
            OR (status = 'completed') = (start_quality = 'fresh' AND end_quality = 'fresh')
        ),
    CONSTRAINT tank_event_fresh_start_has_value
        CHECK (start_quality <> 'fresh' OR start_value_kg IS NOT NULL),
    CONSTRAINT tank_event_fresh_end_has_value
        CHECK (end_quality <> 'fresh' OR end_value_kg IS NOT NULL),
    CONSTRAINT tank_event_completed_has_duration
        CHECK (status <> 'completed' OR duration_ms IS NOT NULL),
    CONSTRAINT tank_event_duration_not_negative
        CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE INDEX tank_event_tank_id_start_at_idx ON dms.tank_event (tank_id, start_at);

GRANT SELECT, INSERT, UPDATE ON dms.tank_event TO dms_writer;
