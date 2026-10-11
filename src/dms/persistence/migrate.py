import sys
from collections.abc import Sequence

import psycopg
import structlog
from psycopg import sql
from psycopg.rows import TupleRow

from dms.config.loader import ConfigError, load_shared
from dms.logs import events
from dms.logs.setup import configure_logging
from dms.persistence.connection import build_conninfo
from dms.persistence.schema import (
    MIGRATION_TABLE,
    SCHEMA_NAME,
    Migration,
    MigrationFilesError,
    load_migrations,
    package_schema_version,
)

OWNER_ROLE = "dms_owner"
MIGRATION_LOCK_KEY = 7_156_001
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2

MIGRATION_TABLE_SQL = sql.SQL(
    "CREATE TABLE IF NOT EXISTS {table} ("
    " version integer PRIMARY KEY,"
    " name text NOT NULL,"
    " checksum text NOT NULL,"
    " schema_version text NOT NULL,"
    " applied_at timestamptz NOT NULL)"
).format(table=sql.Identifier(SCHEMA_NAME, MIGRATION_TABLE))
MIGRATION_TABLE_GRANT_SQL = sql.SQL("GRANT SELECT ON {table} TO dms_read, dms_writer").format(
    table=sql.Identifier(SCHEMA_NAME, MIGRATION_TABLE)
)
RECORD_MIGRATION_SQL = sql.SQL(
    "INSERT INTO {table} (version, name, checksum, schema_version, applied_at)"
    " VALUES (%s, %s, %s, %s, now())"
).format(table=sql.Identifier(SCHEMA_NAME, MIGRATION_TABLE))
APPLIED_MIGRATIONS_SQL = sql.SQL(
    "SELECT version, name, checksum FROM {table} ORDER BY version"
).format(table=sql.Identifier(SCHEMA_NAME, MIGRATION_TABLE))


class ChecksumMismatchError(Exception):
    def __init__(self, files: list[str]) -> None:
        super().__init__(f"applied migration files were changed: {', '.join(files)}")
        self.files = files


class DatabaseAheadError(Exception):
    def __init__(self, migrations: list[str]) -> None:
        super().__init__(
            f"database has migrations unknown to this package: {', '.join(migrations)}"
        )
        self.migrations = migrations


def apply_migrations(
    connection: psycopg.Connection[TupleRow], migrations: Sequence[Migration]
) -> list[Migration]:
    logger = structlog.get_logger()
    connection.execute("SELECT pg_advisory_lock(%s)", [MIGRATION_LOCK_KEY])
    try:
        with connection.transaction():
            connection.execute(MIGRATION_TABLE_SQL)
            connection.execute(MIGRATION_TABLE_GRANT_SQL)
        applied_rows = connection.execute(APPLIED_MIGRATIONS_SQL).fetchall()
        _check_applied_migrations(applied_rows, migrations)
        applied_versions = {row[0] for row in applied_rows}
        pending = [
            migration for migration in migrations if migration.version not in applied_versions
        ]
        for migration in pending:
            with connection.transaction():
                connection.execute(migration.sql.encode())
                connection.execute(
                    RECORD_MIGRATION_SQL,
                    [
                        migration.version,
                        migration.name,
                        migration.checksum,
                        str(migration.schema_version),
                    ],
                )
            logger.info(
                events.MIGRATE_APPLIED,
                migration=f"{migration.version:04d}_{migration.name}",
                schema_version=str(migration.schema_version),
            )
        logger.info(
            events.MIGRATE_DONE,
            schema_version=str(package_schema_version(migrations)),
            applied_count=len(pending),
        )
        return pending
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", [MIGRATION_LOCK_KEY])


def _check_applied_migrations(
    applied_rows: Sequence[TupleRow], migrations: Sequence[Migration]
) -> None:
    known = {migration.version: migration for migration in migrations}
    unknown = [f"{version:04d}_{name}" for version, name, _ in applied_rows if version not in known]
    if unknown:
        raise DatabaseAheadError(unknown)
    changed = [
        f"{version:04d}_{name}.sql"
        for version, name, checksum in applied_rows
        if known[version].checksum != checksum
    ]
    if changed:
        raise ChecksumMismatchError(changed)


def main() -> int:
    try:
        shared = load_shared()
    except ConfigError as error:
        for line in error.errors:
            print(line, file=sys.stderr)
        return EXIT_CONFIG_ERROR
    configure_logging(shared.logging.level, shared.logging.format)
    logger = structlog.get_logger()
    try:
        migrations = load_migrations()
        with psycopg.connect(build_conninfo(shared.database, OWNER_ROLE), autocommit=True) as conn:
            apply_migrations(conn, migrations)
    except MigrationFilesError as error:
        logger.critical(events.DB_STARTUP_FAILED, step="load_migrations", error=str(error))
    except ChecksumMismatchError as error:
        logger.critical(events.MIGRATE_CHECKSUM_MISMATCH, files=error.files)
    except DatabaseAheadError as error:
        logger.critical(events.MIGRATE_DATABASE_AHEAD, migrations=error.migrations)
    except psycopg.Error as error:
        logger.critical(events.DB_STARTUP_FAILED, step="migrate", error=str(error))
    else:
        return 0
    return EXIT_FAILURE
