import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from typing import NamedTuple

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow

SCHEMA_NAME = "dms"
MIGRATION_TABLE = "schema_migration"
MIGRATION_FILE_PATTERN = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
CHANGE_HEADER_PATTERN = re.compile(r"^-- schema-change: (major|minor|patch)$")
SCHEMA_VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LATEST_SCHEMA_VERSION_SQL = "SELECT schema_version FROM {table} ORDER BY version DESC LIMIT 1"
FIRST_MIGRATION_VERSION = 1


class ChangeKind(StrEnum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


class SchemaVersionFormatError(Exception):
    pass


class SchemaVersion(NamedTuple):
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> SchemaVersion:
        match = SCHEMA_VERSION_PATTERN.match(text)
        if match is None:
            raise SchemaVersionFormatError(
                f"schema version '{text}' must look like MAJOR.MINOR.PATCH"
            )
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major, minor, patch)

    def bumped(self, change: ChangeKind) -> SchemaVersion:
        if change == ChangeKind.MAJOR:
            return SchemaVersion(self.major + 1, 0, 0)
        if change == ChangeKind.MINOR:
            return SchemaVersion(self.major, self.minor + 1, 0)
        return SchemaVersion(self.major, self.minor, self.patch + 1)


INITIAL_VERSION = SchemaVersion(0, 0, 0)


@dataclass(frozen=True, slots=True, kw_only=True)
class Migration:
    version: int
    name: str
    sql: str
    checksum: str
    change: ChangeKind
    schema_version: SchemaVersion


class MigrationFilesError(Exception):
    pass


class SchemaIncompatibleError(Exception):
    def __init__(
        self, database_version: SchemaVersion | None, package_version: SchemaVersion
    ) -> None:
        found = "no schema_migration table" if database_version is None else str(database_version)
        super().__init__(
            f"database schema {found} is not compatible with package {package_version}"
        )
        self.database_version = database_version
        self.package_version = package_version


def packaged_migrations_directory() -> Traversable:
    return resources.files("dms.persistence") / "migrations"


def load_migrations(directory: Traversable | None = None) -> list[Migration]:
    source = directory if directory is not None else packaged_migrations_directory()
    files = sorted(
        (entry for entry in source.iterdir() if entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    migrations: list[Migration] = []
    current_version = INITIAL_VERSION
    for expected_number, entry in enumerate(files, start=FIRST_MIGRATION_VERSION):
        match = MIGRATION_FILE_PATTERN.match(entry.name)
        if match is None:
            raise MigrationFilesError(f"{entry.name}: name must look like NNNN_name.sql")
        if int(match.group(1)) != expected_number:
            raise MigrationFilesError(
                f"{entry.name}: expected number {expected_number:04d}, numbers must be continuous"
            )
        raw = entry.read_bytes()
        try:
            sql_text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MigrationFilesError(f"{entry.name}: not valid UTF-8 ({error})") from error
        change = _read_change_kind(entry.name, sql_text)
        current_version = current_version.bumped(change)
        migrations.append(
            Migration(
                version=expected_number,
                name=match.group(2),
                sql=sql_text,
                checksum=hashlib.sha256(raw).hexdigest(),
                change=change,
                schema_version=current_version,
            )
        )
    return migrations


def _read_change_kind(file_name: str, sql_text: str) -> ChangeKind:
    first_line = sql_text.splitlines()[0] if sql_text else ""
    match = CHANGE_HEADER_PATTERN.match(first_line)
    if match is None:
        raise MigrationFilesError(
            f"{file_name}: first line must be '-- schema-change: major|minor|patch'"
        )
    return ChangeKind(match.group(1))


def package_schema_version(migrations: Sequence[Migration] | None = None) -> SchemaVersion:
    known = migrations if migrations is not None else load_migrations()
    return known[-1].schema_version if known else INITIAL_VERSION


def is_compatible(database: SchemaVersion, package: SchemaVersion) -> bool:
    return database.major == package.major and database.minor >= package.minor


def database_schema_version(connection: psycopg.Connection[TupleRow]) -> SchemaVersion | None:
    table_exists = connection.execute(
        "SELECT to_regclass(%s) IS NOT NULL", [f"{SCHEMA_NAME}.{MIGRATION_TABLE}"]
    ).fetchone()
    if table_exists is None or not table_exists[0]:
        return None
    row = connection.execute(
        sql.SQL(LATEST_SCHEMA_VERSION_SQL).format(
            table=sql.Identifier(SCHEMA_NAME, MIGRATION_TABLE)
        )
    ).fetchone()
    return SchemaVersion.parse(row[0]) if row is not None else INITIAL_VERSION


def check_schema_compatible(connection: psycopg.Connection[TupleRow]) -> SchemaVersion:
    package_version = package_schema_version()
    database_version = database_schema_version(connection)
    if database_version is None or not is_compatible(database_version, package_version):
        raise SchemaIncompatibleError(database_version, package_version)
    return database_version
