-- schema-change: minor

ALTER TABLE dms.tank_event
    ADD COLUMN rule_violation boolean,
    ADD COLUMN collision boolean,
    ADD CONSTRAINT tank_event_in_progress_has_no_flags
        CHECK (status <> 'in_progress' OR (rule_violation IS NULL AND collision IS NULL));
