from psycopg.conninfo import make_conninfo

from dms.config.models import DatabaseConfig


def build_conninfo(database: DatabaseConfig, role: str) -> str:
    return make_conninfo(host=database.host, port=database.port, dbname=database.dbname, user=role)
