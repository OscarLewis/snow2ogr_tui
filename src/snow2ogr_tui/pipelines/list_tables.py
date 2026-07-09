"""Utilities for listing tables in a Snowflake database/schema.

Provides list_tables() which queries INFORMATION_SCHEMA.TABLES to return
pairs of (table_name, created) for a given database and schema.
"""

import re
from datetime import datetime

import adbc_driver_snowflake.dbapi


def list_tables(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    like: str | list[str] | None = None,
) -> list[tuple[str, datetime | None]]:
    """List ``(table_name, created)`` pairs in ``database.schema`` via INFORMATION_SCHEMA."""
    safe_database = _quote_ident(database)
    patterns = [like] if isinstance(like, str) else list(like or [])

    sql = f"SELECT TABLE_NAME, CREATED FROM {safe_database}.INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = ?"
    params: list[str] = [schema]

    if patterns:
        sql += " AND (" + " OR ".join("TABLE_NAME LIKE ?" for _ in patterns) + ")"
        params.extend(str(p).upper() for p in patterns)

    sql += " ORDER BY CREATED DESC"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [(row[0], row[1]) for row in cur.fetchall()]


_UNQUOTED_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _quote_ident(name: str) -> str:
    """Safely quote a SQL identifier (database/schema/table name) for interpolation."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid identifier: {name!r}")
    if not _UNQUOTED_IDENT_RE.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'
