DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dms_owner') THEN
        CREATE ROLE dms_owner LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dms_writer') THEN
        CREATE ROLE dms_writer LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dms_read') THEN
        CREATE ROLE dms_read NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dms_api') THEN
        CREATE ROLE dms_api LOGIN;
    END IF;
    IF NOT pg_has_role('dms_api', 'dms_read', 'MEMBER') THEN
        GRANT dms_read TO dms_api;
    END IF;
END
$$;
