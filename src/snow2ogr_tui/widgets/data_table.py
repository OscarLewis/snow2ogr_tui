"""Vim-style data table widget for the Snow2OGR TUI."""

import asyncio
from datetime import datetime
from typing import Any, ClassVar, Literal

import adbc_driver_snowflake.dbapi
from adbc_driver_manager.dbapi import (
    DatabaseError,
    OperationalError,
    ProgrammingError,
)
from loguru import logger
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Middle, Vertical
from textual.message import Message
from textual.widgets import LoadingIndicator, Static
from textual_fastdatatable import DataTable

from snow2ogr_tui.pipelines.list_tables import list_tables

COLUMNS = ("Table Name", "Creation Date")


# Add this message class near the top of your file, after imports
class TablesLoaded(Message):
    """Posted when table data has been successfully loaded."""

    def __init__(self, table_data: list[tuple[str, datetime | None]]) -> None:
        """Initialize the message/event with the loaded table data."""
        self.table_data = table_data
        super().__init__()


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
                adbc_driver_snowflake.dbapi.connect,
                db_kwargs={
                    "adbc.snowflake.sql.account": "ist-acdp01",
                    "username": "oscar_lewis@apple.com",
                    "adbc.snowflake.sql.auth_type": "auth_ext_browser",
                    "adbc.snowflake.sql.db": "MAPS_DATA_SEMANTIC_DB",
                    "adbc.snowflake.sql.schema": "TERRITORY_APP",
                    "adbc.snowflake.sql.warehouse": "MAPS_DATA_TERRITORIES_ADHOC_VWH",
                    "adbc.snowflake.sql.role": "MAPS_DATA_CPMA_TEAM_ROLE",
                },
            )
            tables = await asyncio.to_thread(
                list_tables,
                conn,
                "MAPS_DATA_SEMANTIC_DB",
                "TERRITORY_APP",
            )
        except OperationalError:
            logger.exception("Failed to connect to Snowflake.")
        except ProgrammingError:
            logger.exception(
                "Snowflake reported a SQL error while listing tables.",
            )
        except DatabaseError:
            logger.exception(
                "Snowflake returned a database error while listing tables.",
            )
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

            # Post message that data has been loaded
            self.post_message(TablesLoaded(tables))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Log the selected row's data on Enter or click."""
        row_index = event.cursor_row
        if 0 <= row_index < len(self.table_data):
            name, created = self.table_data[row_index]
            logger.info(
                f"Row selected: index={row_index} name={name!r} created={created}",
            )
        else:
            logger.warning(f"Invalid row index: {row_index}")
