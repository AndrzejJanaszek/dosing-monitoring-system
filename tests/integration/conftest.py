import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import TupleRow
from testcontainers.community.postgres import PostgresContainer

DB_SCRIPTS_DIR = Path(__file__).parents[2] / "scripts" / "db"
POSTGRES_IMAGE = "postgres:18"
SERVER_URL_VARIABLE = "DMS_TEST_PG_URL"


def read_db_script(name: str) -> bytes:
    return (DB_SCRIPTS_DIR / name).read_bytes()


@pytest.fixture(scope="session")
def pg_server() -> Iterator[str]:
    server_url = os.environ.get(SERVER_URL_VARIABLE)
    if server_url:
        yield server_url
        return
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def dms_database(pg_server: str) -> Iterator[str]:
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


@pytest.fixture
def roles_script() -> bytes:
    return read_db_script("roles.sql")


@pytest.fixture
def dms_connection(dms_database: str) -> Iterator[psycopg.Connection[TupleRow]]:
    connection = psycopg.connect(dms_database)
    try:
        yield connection
    finally:
        connection.close()
