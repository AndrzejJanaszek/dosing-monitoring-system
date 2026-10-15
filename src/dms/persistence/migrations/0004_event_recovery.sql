-- schema-change: minor

ALTER TYPE dms.end_quality ADD VALUE 'record_rejected';

GRANT SELECT ON dms.meter_reading TO dms_writer;
