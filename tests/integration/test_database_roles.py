import psycopg
import pytest
from psycopg import errors
from psycopg.rows import TupleRow

from tests.database import set_role

LOGIN_ROLES = ("dms_owner", "dms_writer", "dms_api")
ALL_ROLES = (*LOGIN_ROLES, "dms_read")
ROLES_WITHOUT_DDL_IN_DMS = ("dms_writer", "dms_read", "dms_api")


def test_roles_have_expected_attributes(dms_connection: psycopg.Connection[TupleRow]) -> None:
    rows = dms_connection.execute(
        "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole"
        " FROM pg_roles WHERE rolname = ANY(%s)",
        [list(ALL_ROLES)],
    ).fetchall()

    assert {name: attributes for name, *attributes in rows} == {
        "dms_owner": [True, False, False, False],
        "dms_writer": [True, False, False, False],
        "dms_api": [True, False, False, False],
        "dms_read": [False, False, False, False],
    }


def test_api_role_is_member_of_read_role(dms_connection: psycopg.Connection[TupleRow]) -> None:
    row = dms_connection.execute("SELECT pg_has_role('dms_api', 'dms_read', 'MEMBER')").fetchone()

    assert row == (True,)


@pytest.mark.parametrize("role", LOGIN_ROLES)
def test_login_role_can_connect_to_database(
    dms_connection: psycopg.Connection[TupleRow], role: str
) -> None:
    row = dms_connection.execute(
        "SELECT has_database_privilege(%s, current_database(), 'CONNECT')", [role]
    ).fetchone()

    assert row == (True,)


def test_public_cannot_connect_to_database(dms_connection: psycopg.Connection[TupleRow]) -> None:
    row = dms_connection.execute(
        "SELECT has_database_privilege('public', current_database(), 'CONNECT')"
    ).fetchone()

    assert row == (False,)


def test_owner_role_owns_dms_schema(dms_connection: psycopg.Connection[TupleRow]) -> None:
    row = dms_connection.execute(
        "SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'dms'"
    ).fetchone()

    assert row == ("dms_owner",)


def test_owner_role_can_create_table_in_dms_schema(
    dms_connection: psycopg.Connection[TupleRow],
) -> None:
    set_role(dms_connection, "dms_owner")

    dms_connection.execute("CREATE TABLE dms.probe (id integer)")


@pytest.mark.parametrize("role", ROLES_WITHOUT_DDL_IN_DMS)
def test_role_cannot_create_table_in_dms_schema(
    dms_connection: psycopg.Connection[TupleRow], role: str
) -> None:
    set_role(dms_connection, role)

    with pytest.raises(errors.InsufficientPrivilege):
        dms_connection.execute("CREATE TABLE dms.probe (id integer)")


@pytest.mark.parametrize("role", ALL_ROLES)
def test_role_cannot_create_table_in_public_schema(
    dms_connection: psycopg.Connection[TupleRow], role: str
) -> None:
    set_role(dms_connection, role)

    with pytest.raises(errors.InsufficientPrivilege):
        dms_connection.execute("CREATE TABLE public.probe (id integer)")


def test_roles_script_can_run_again(
    dms_connection: psycopg.Connection[TupleRow], roles_script: bytes
) -> None:
    dms_connection.execute(roles_script)
