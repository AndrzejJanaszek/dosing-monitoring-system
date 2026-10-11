import hashlib
from pathlib import Path

import pytest

from dms.persistence.schema import (
    INITIAL_VERSION,
    MigrationFilesError,
    SchemaVersion,
    is_compatible,
    load_migrations,
    package_schema_version,
)


def write_migration(directory: Path, file_name: str, change: str = "minor") -> None:
    (directory / file_name).write_text(f"-- schema-change: {change}\nSELECT 1;\n", encoding="utf-8")


def test_packaged_migrations_load_and_start_with_init() -> None:
    migrations = load_migrations()

    assert migrations[0].name == "init"
    assert migrations[0].schema_version == SchemaVersion(1, 0, 0)


def test_checksum_is_sha256_of_raw_bytes(tmp_path: Path) -> None:
    write_migration(tmp_path, "0001_init.sql", "major")

    (migration,) = load_migrations(tmp_path)

    assert (
        migration.checksum == hashlib.sha256((tmp_path / "0001_init.sql").read_bytes()).hexdigest()
    )


def test_versions_are_computed_from_headers_in_order(tmp_path: Path) -> None:
    for file_name, change in [
        ("0001_init.sql", "major"),
        ("0002_add_a.sql", "minor"),
        ("0003_add_b.sql", "minor"),
        ("0004_fix.sql", "patch"),
        ("0005_break.sql", "major"),
        ("0006_add_c.sql", "minor"),
    ]:
        write_migration(tmp_path, file_name, change)

    migrations = load_migrations(tmp_path)

    assert [str(migration.schema_version) for migration in migrations] == [
        "1.0.0",
        "1.1.0",
        "1.2.0",
        "1.2.1",
        "2.0.0",
        "2.1.0",
    ]
    assert package_schema_version(migrations) == SchemaVersion(2, 1, 0)


def test_empty_directory_gives_initial_version(tmp_path: Path) -> None:
    assert package_schema_version(load_migrations(tmp_path)) == INITIAL_VERSION


def test_missing_header_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "0001_init.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(MigrationFilesError, match=r"0001_init\.sql"):
        load_migrations(tmp_path)


def test_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "0001_init.sql").write_bytes(b"-- schema-change: major\nSELECT '\xff';\n")

    with pytest.raises(MigrationFilesError, match=r"0001_init\.sql: not valid UTF-8"):
        load_migrations(tmp_path)


def test_unknown_change_kind_is_rejected(tmp_path: Path) -> None:
    write_migration(tmp_path, "0001_init.sql", "huge")

    with pytest.raises(MigrationFilesError, match="first line"):
        load_migrations(tmp_path)


def test_gap_in_numbers_is_rejected(tmp_path: Path) -> None:
    write_migration(tmp_path, "0001_init.sql", "major")
    write_migration(tmp_path, "0003_skip.sql")

    with pytest.raises(MigrationFilesError, match=r"0003_skip\.sql"):
        load_migrations(tmp_path)


def test_numbering_must_start_at_one(tmp_path: Path) -> None:
    write_migration(tmp_path, "0002_late.sql", "major")

    with pytest.raises(MigrationFilesError, match=r"0002_late\.sql"):
        load_migrations(tmp_path)


def test_badly_named_file_is_rejected(tmp_path: Path) -> None:
    write_migration(tmp_path, "init.sql", "major")

    with pytest.raises(MigrationFilesError, match=r"init\.sql"):
        load_migrations(tmp_path)


@pytest.mark.parametrize(
    ("database", "package", "compatible"),
    [
        ("1.0.0", "1.0.0", True),
        ("1.3.2", "1.0.0", True),
        ("1.1.0", "1.1.5", True),
        ("1.0.0", "1.1.0", False),
        ("2.0.0", "1.0.0", False),
        ("1.9.0", "2.0.0", False),
        ("0.0.0", "1.0.0", False),
    ],
)
def test_compatibility_rule(database: str, package: str, compatible: bool) -> None:
    assert is_compatible(SchemaVersion.parse(database), SchemaVersion.parse(package)) is compatible


def test_version_text_round_trip() -> None:
    assert str(SchemaVersion.parse("3.14.15")) == "3.14.15"
