DO $$
BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO dms_owner, dms_writer, dms_read', current_database());
END
$$;

CREATE SCHEMA dms AUTHORIZATION dms_owner;
GRANT USAGE ON SCHEMA dms TO dms_writer, dms_read;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
