"""Database setup utilities for the snow2ogr_db_models package.

Provides init_db to create a SQLite engine, enable foreign keys, and
return an engine and sessionmaker.
"""

from pathlib import Path

from sqlalchemy import (
    Engine,
    create_engine,
    event,
)
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)
from sqlalchemy.pool import ConnectionPoolEntry

from snow2ogr_tui.database.models import Base


def init_db(
    db_path: Path,
    *,
    reset: bool = False,
    echo: bool = False,
) -> tuple[Engine, sessionmaker[Session]]:
    """Initialize a SQLite database and return (engine, sessionmaker).

    Args:
        db_path: Path to the SQLite database file.
        reset: If True and the file exists, remove it before creating.
        echo: If True enable SQLAlchemy logging of SQL statements.

    Returns:
        Tuple of (Engine, sessionmaker[Session]).

    """
    db_path = Path(db_path)

    if reset and db_path.exists():
        db_path.unlink()

    engine = create_engine(f"sqlite:///{db_path}", echo=echo)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        dbapi_connection: DBAPIConnection,
        connection_record: ConnectionPoolEntry,  # noqa: ARG001 - I know we're not using this right now.
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    sessionlocal: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=True,
        expire_on_commit=False,
    )

    return engine, sessionlocal
