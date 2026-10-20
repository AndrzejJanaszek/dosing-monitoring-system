import logging
import os
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

import psycopg
import pytest
import structlog
from psycopg.rows import TupleRow
from structlog.testing import capture_logs
from testcontainers.community.postgres import PostgresContainer

from tests.database import migrate_as_owner, read_db_script, temporary_database

TESTS_ROOT = Path(__file__).parent
TEST_LEVELS = ("unit", "integration", "e2e")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        level = item.path.relative_to(TESTS_ROOT).parts[0]
        if level in TEST_LEVELS:
            item.add_marker(level)


POSTGRES_IMAGE = "postgres:18"
SERVER_URL_VARIABLE = "DMS_TEST_PG_URL"


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
    with temporary_database(pg_server) as database_url:
        yield database_url


@pytest.fixture(scope="session")
def migrated_database(dms_database: str) -> str:
    migrate_as_owner(dms_database)
    return dms_database


@pytest.fixture
def fresh_database(pg_server: str) -> Iterator[str]:
    with temporary_database(pg_server) as database_url:
        yield database_url


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


@pytest.fixture
def migrated_connection(migrated_database: str) -> Iterator[psycopg.Connection[TupleRow]]:
    connection = psycopg.connect(migrated_database)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()


@pytest.fixture
def logs() -> Iterator[list[MutableMapping[str, Any]]]:
    with capture_logs() as captured:
        yield captured
