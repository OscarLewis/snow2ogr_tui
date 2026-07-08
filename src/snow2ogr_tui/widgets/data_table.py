"""Vim-style data table widget for the Snow2OGR TUI."""

import asyncio
import re
from datetime import datetime
from typing import Any, ClassVar, Literal

import snowflake.connector
from loguru import logger
from snowflake.connector import SnowflakeConnection
from snowflake.connector.errors import DatabaseError, OperationalError, ProgrammingError
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Middle, Vertical
from textual.widgets import LoadingIndicator, Static
from textual_fastdatatable import DataTable

COLUMNS = ("Table Name", "Creation Date")


class VimStyleTable(DataTable):
    """DataTable with Vim-style navigation bindings."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("j", "cursor_down", "Cursor down", show=False),
        Binding("k", "cursor_up", "Cursor up", show=False),
        Binding("h", "cursor_left", "Cursor left", show=False),
        Binding("l", "cursor_right", "Cursor right", show=False),
    ]


class VimDataTable(Container):
    """A container with a data table and loading indicator using Vim-style bindings."""

    # Explicitly configure the z-index layers via basic CSS
    CSS = """
    VimDataTable {
        layers: base top;
    }
    #data-table {
        layer: base;
        height: 100%;
    }
    #loading-overlay {
        layer: top;
        width: 100%;
        height: 100%;
        background: $background;
    }
    """

    def __init__(
        self,
        *args: Any,  # noqa: ANN401 since we are creating a Container sub-class
        cursor_type: Literal["cell", "row", "column", "none"] = "row",
        **kwargs,
    ) -> None:
        """Initialize VimDataTable with DataTable parameters."""
        super().__init__(*args, **kwargs)
        self.cursor_type = cursor_type
        self.table_data: list[tuple[str, datetime | None]] = []  # Store the table data here

    def compose(self) -> ComposeResult:
        """Create the layout with data table and loading indicator."""
        yield VimStyleTable(id="data-table", cursor_type=self.cursor_type)

        # Root container handles background layer
        overlay = Container(id="loading-overlay")

        # Middle handles vertical centering, Center handles horizontal centering
        middle_container = Middle()
        center_container = Center()

        # Build a simple vertical stack for text + dots
        content_stack = Vertical()
        content_stack.styles.width = "auto"
        content_stack.styles.height = "auto"

        text = Static("Fetching Snowflake tables...", id="loading-text")
        text.styles.text_align = "center"
        text.styles.width = "auto"
        text.styles.margin = (0, 0, 1, 0)  # 1 line spacing below text

        indicator = LoadingIndicator(id="loading-indicator")
        indicator.styles.height = 1
        indicator.styles.width = "100%"
        indicator.styles.align_horizontal = "center"

        # Nest them sequentially to enforce layout behavior
        with overlay, middle_container, center_container, content_stack:
            yield text
            yield indicator

    def on_mount(self) -> None:
        """Set up the table and start fetching data."""
        self.fetch_data()

    @work(exclusive=True)
    async def fetch_data(self) -> None:
        """Fetch remote data and populate the table."""
        conn = None
        tables: list[tuple[str, datetime | None]] = []
        try:
            conn = await asyncio.to_thread(
                snowflake.connector.connect,
                account="ist-acdp01",
                user="oscar_lewis@apple.com",
                authenticator="externalbrowser",
                database="MAPS_DATA_SEMANTIC_DB",
                schema="TERRITORY_APP",
                warehouse="MAPS_DATA_TERRITORIES_ADHOC_VWH",
                role="MAPS_DATA_CPMA_TEAM_ROLE",
            )
            tables = await asyncio.to_thread(
                list_tables,
                conn,
                "MAPS_DATA_SEMANTIC_DB",
                "TERRITORY_APP",
            )
        except OperationalError as oe:
            # Network drops, timeout errors, or Snowflake endpoints unreachable
            logger.error(f"Network or Connection Error: {oe.msg} (Code: {oe.errno})")
            # Optional: update a TUI banner to show "Offline/Network issue"
        except ProgrammingError as pe:
            # SQL compilation errors, bad permissioning, or missing database objects
            logger.error(f"SQL or Permission Error: {pe.msg} (SQLState: {pe.sqlstate})")
            # Optional: notify user via TUI that they lack role permissions
        except DatabaseError as de:
            # Catch-all for other underlying Snowflake-specific backend exceptions
            logger.error(f"Snowflake Database Error: {de.msg}")
        finally:
            if conn is not None:
                await asyncio.to_thread(conn.close)

            # Store data for later lookup
            self.table_data = tables

            # Hide loading indicator and populate table
            loading_overlay = self.query_one("#loading-overlay")
            loading_overlay.display = False

            table = self.query_one("#data-table", VimStyleTable)

            # Calculate widths based on available space
            available_width = table.size.width - 6  # Subtract for padding and borders
            table_name_width = int(available_width * 0.7)
            creation_date_width = available_width - table_name_width

            table.add_column("Table Name", width=table_name_width)
            table.add_column("Creation Date", width=creation_date_width)
            table.add_rows(
                [[name, created.strftime("%Y-%m-%d %H:%M:%S") if created else ""] for name, created in tables],
            )

            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Log the selected row's data on Enter or click."""
        row_index = event.cursor_row
        if 0 <= row_index < len(self.table_data):
            name, created = self.table_data[row_index]
            logger.debug(
                f"Row selected: index={row_index} name={name!r} created={created}",
            )
        else:
            logger.warning(f"Invalid row index: {row_index}")


def list_tables(
    conn: SnowflakeConnection,
    database: str,
    schema: str,
    like: str | list[str] | None = None,
) -> list[tuple[str, datetime | None]]:
    """List ``(table_name, created)`` pairs in ``database.schema`` via INFORMATION_SCHEMA."""
    safe_database = _quote_ident(database)
    patterns = [like] if isinstance(like, str) else list(like or [])

    sql = (
        f"SELECT TABLE_NAME, CREATED FROM {safe_database}.INFORMATION_SCHEMA.TABLES "  # noqa: S608
        "WHERE TABLE_SCHEMA = %s"
    )
    params = [schema]
    if patterns:
        sql += " AND (" + " OR ".join("TABLE_NAME LIKE %s" for _ in patterns) + ")"
        params.extend(str(p).upper() for p in patterns)
    sql += " ORDER BY CREATED DESC"

    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return [(row[0], row[1]) for row in cur.fetchall()]
    finally:
        cur.close()


_UNQUOTED_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def _quote_ident(name: str) -> str:
    """Safely quote a SQL identifier (database/schema/table name) for interpolation."""
    if not isinstance(name, str) or not name:
        msg = f"Invalid identifier: {name!r}"
        raise ValueError(msg)
    if not _UNQUOTED_IDENT_RE.match(name):
        msg_0 = f"Invalid identifier: {name!r}"
        raise ValueError(msg_0)
    return '"' + name.replace('"', '""') + '"'
