import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import TupleRow

from dms.persistence.migrate import apply_migrations
from dms.persistence.schema import load_migrations

DB_SCRIPTS_DIR = Path(__file__).parents[1] / "scripts" / "db"


def read_db_script(name: str) -> bytes:
    return (DB_SCRIPTS_DIR / name).read_bytes()


@contextmanager
def temporary_database(pg_server: str) -> Iterator[str]:
    database_name = f"dms_test_{secrets.token_hex(4)}"
    database_identifier = sql.Identifier(database_name)
    with psycopg.connect(pg_server, autocommit=True) as server:
        server.execute(read_db_script("roles.sql"))
        server.execute(sql.SQL("CREATE DATABASE {}").format(database_identifier))
        try:
            database_url = make_conninfo(pg_server, dbname=database_name)
            with psycopg.connect(database_url) as database:
                database.execute(read_db_script("database.sql"))
            yield database_url
        finally:
            server.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(database_identifier))


def migrate_as_owner(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SET ROLE dms_owner")
        apply_migrations(connection, load_migrations())


def connect_as(database_url: str, role: str) -> psycopg.Connection[TupleRow]:
    connection = psycopg.connect(database_url, autocommit=True)
    set_role(connection, role)
    return connection


def set_role(connection: psycopg.Connection[TupleRow], role: str) -> None:
    connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
