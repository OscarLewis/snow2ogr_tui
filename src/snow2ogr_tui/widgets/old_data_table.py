"""Vim-style data table widget for the Snow2OGR TUI."""

# ruff: noqa: ERA001 - I know there's commented out code in here.

import asyncio
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

import polars as pl
from adbc_driver_manager.dbapi import (
    DatabaseError,
    OperationalError,
    ProgrammingError,
)
from adbc_driver_snowflake.dbapi import Connection
from loguru import logger
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Middle, Vertical
from textual.events import Resize
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import LoadingIndicator, Static
from textual_fastdatatable import DataTable

from snow2ogr_tui.common.models import FilterType, TableSet
from snow2ogr_tui.pipelines.group_tables import group_territory_tables, preprocess_table_metadata
from snow2ogr_tui.pipelines.list_tables import list_tables
from snow2ogr_tui.widgets.downloader_screen import DownloaderScreen

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


COLUMNS = ("Table Name", "Creation Date")


# Add this message class near the top of your file, after imports
class TablesLoaded(Message):
    """Posted when table data has been successfully loaded."""

    def __init__(self, table_data: list[tuple[str, datetime | None]]) -> None:
        """Initialize the message/event with the loaded table data."""
        super().__init__()

        self.table_data = table_data


class FilterToggled(Message):
    """Posted when the table filter should be toggled."""

    def __init__(self, filter_type: FilterType | None = None) -> None:
        """Initialize the message with the new filter type.

        Args:
            filter_type: The filter to apply (FilterType.NDMGEO or None for no filter).

        """
        super().__init__()

        self.filter_type = filter_type


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
    DEFAULT_CSS = """
    VimDataTable {
        layers: base top;
    }
    VimDataTable #filter-indicator {
        layer: base;
        height: 1;
        dock: top;
        width: auto;
        padding: 0 1;
    }
    VimDataTable #data-table {
        height: 1fr;
        layer:base
    }
    VimDataTable #loading-overlay {
        layer: top;
        width: 100%;
        height: 100%;
        background: $background;
    }
    """

    # Was the initial table load from Snowflake completed successfully?
    table_loaded = reactive(False)  # noqa: FBT003 - I am intentionally setting this to default to False
    current_table_revision = reactive(0)

    def __init__(
        self,
        *args: Any,  # noqa: ANN401 since we are creating a Container sub-class
        cursor_type: Literal["cell", "row", "column", "none"] = "row",
        **kwargs,
    ) -> None:
        """Initialize VimDataTable with DataTable parameters."""
        super().__init__(*args, **kwargs)
        self.cursor_type = cursor_type
        self.current_filter: FilterType = FilterType.NDMGEO  # Track current filter state
        self.table_pl_grouped: pl.DataFrame = pl.DataFrame()
        self.table_pl_pre: pl.DataFrame = pl.DataFrame()
        self.current_table: pl.DataFrame = pl.DataFrame()

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    @property
    def sf_connection(self) -> Connection | None:
        """Return the application's current Snowflake connection."""
        return self.tui_app.sf_conn

    def compose(self) -> ComposeResult:
        """Create the layout with data table and loading indicator."""
        # Add filter indicator at the top
        filter_indicator = Static("Filter: NDM/GEO", id="filter-indicator")
        yield filter_indicator

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

    def on_resize(self, event: Resize) -> None:
        """Handle resize events."""
        logger.debug(f"Resize: {self.size}")

    def on_show(self) -> None:
        """Handle show events and log widget size."""
        logger.debug(f"Show: {self.size}")
        # TODO: Create table in view here instead of in fetch_data

    #     self._resize_columns()

    # def _resize_columns(self) -> None:
    #     try:
    #         table = self.query_one("#data-table", VimStyleTable)
    #     except Exception:
    #         return

    #     if not table.columns:
    #         return

    #     available_width = table.size.width - 6
    #     table_name_width = int(available_width * 0.7)
    #     creation_date_width = available_width - table_name_width

    #     table.columns["Table Name"].width = table_name_width
    #     table.columns["Creation Date"].width = creation_date_width

    def on_mount(self) -> None:
        """Set up the table."""
        # self._refresh_table_with_filter()

    @work(exclusive=True)
    async def fetch_data(self) -> None:
        """Fetch remote data and populate the table."""
        tables: list[tuple[str, datetime | None]] = []
        conn = self.sf_connection
        if conn is None:
            logger.warning("No active Snowflake connection.")
            return
        try:
            logger.debug("Attempting to list tables in Snowflake")
            self.schema = "TERRITORY_APP"
            self.database = "MAPS_DATA_SEMANTIC_DB"
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
            # Hide loading indicator and populate table
            loading_overlay = self.query_one("#loading-overlay")
            loading_overlay.display = False

            table = self.query_one("#data-table", VimStyleTable)

            # Calculate widths based on available space
            available_width = table.size.width - 6  # Subtract for padding and borders
            table_name_width = int(available_width * 0.7)
            creation_date_width = available_width - table_name_width

            # Create a new pl.DataFrame containing each name and creation date
            table_pl = pl.DataFrame(
                tables,
                schema=["Table Name", "Creation Date"],
                orient="row",
            )
            # Group rows together by a Group Key (normalized name of the tables)
            table_pl_pre = preprocess_table_metadata(table_pl)
            table_pl_grouped = group_territory_tables(table_pl_pre)
            table_pl_grouped = table_pl_grouped.sort("territory_table_creation_date", descending=True)

            # Save the table as a pl.Dataframe for later
            self.table_pl_grouped = table_pl_grouped
            self.table_pl_pre = table_pl_pre.rename(
                {"Table Name": "territory_table_primary", "Creation Date": "territory_table_creation_date"},
            )

            logger.debug(f"Pre-Grouped DF Shape: {self.table_pl_pre.shape}")
            logger.debug(f"Pre-Grouped DF Columns: {self.table_pl_pre.columns}")
            logger.debug(f"New table size: {table.size}")
            logger.debug(f"New virtual table size: {table.virtual_size}")

            table.add_column("Table Name", width=table_name_width)
            table.add_column("Creation Date", width=creation_date_width)
            self.current_table = table_pl_grouped

            logger.debug(f"Grouped DF Shape: {self.table_pl_grouped.shape}")
            logger.debug(f"Grouped DF Columns: {self.table_pl_grouped.columns}")

            # Add rows from Polars
            table.add_rows(
                [
                    [
                        row["territory_table_primary"],
                        row["territory_table_creation_date"].strftime("%Y-%m-%d %H:%M:%S")
                        if row["territory_table_creation_date"]
                        else "",
                    ]
                    for row in (table_pl_grouped.iter_rows(named=True))
                ],
            )

            self.call_after_refresh(table.focus)

            # Post message that data has been loaded
            self.post_message(TablesLoaded(tables))

    def on_filter_toggled(self, message: FilterToggled) -> None:  # noqa: ARG002 - I know we don't touch the message content
        """Handle filter toggle message and refresh the table."""
        # Cycle through filters: None -> NDMGEO -> None
        if self.current_filter == FilterType.RAW:
            self.current_filter = FilterType.NDMGEO
        else:
            self.current_filter = FilterType.RAW
        self._refresh_table_with_filter()

    def _refresh_table_with_filter(self) -> None:
        """Refresh the table with the current filter applied."""
        if self.table_pl_grouped is None or self.table_pl_pre is None:
            msg = "Attempted to refresh table with no data loaded."
            raise RuntimeError(msg)
        # Apply filter to the grouped table
        filtered_table = self.table_pl_pre.clone()

        # Unmount the old table
        old_table = self.query_one(VimStyleTable)
        old_table.remove()

        # Create and mount a new table with filtered data
        new_table = VimStyleTable(cursor_type=self.cursor_type)

        # Calculate column widths
        available_width = self.size.width - 6  # Subtract for padding and borders
        table_name_width = int(available_width * 0.7)
        creation_date_width = available_width - table_name_width
        logger.debug(f"New table size: {new_table.size}")
        logger.debug(f"New virtual table size: {new_table.virtual_size}")
        new_table.add_column("Table Name", width=table_name_width)
        new_table.add_column("Creation Date", width=creation_date_width)

        if self.current_filter == FilterType.NDMGEO:
            self.current_table = self.table_pl_grouped
            new_table.add_rows(
                [
                    [
                        row["territory_table_primary"],
                        row["territory_table_creation_date"].strftime("%Y-%m-%d %H:%M:%S")
                        if row["territory_table_creation_date"]
                        else "",
                    ]
                    for row in (self.table_pl_grouped.iter_rows(named=True))
                ],
            )
        elif self.current_filter == FilterType.RAW:
            # Add rows from filtered Polars DataFrame
            self.current_table = filtered_table
            new_table.add_rows(
                [
                    [
                        row["territory_table_primary"],
                        row["territory_table_creation_date"].strftime("%Y-%m-%d %H:%M:%S")
                        if row["territory_table_creation_date"]
                        else "",
                    ]
                    for row in (filtered_table.iter_rows(named=True))
                ],
            )

        # Mount the new table back as a child of VimDataTable
        self.mount(new_table)
        self.call_after_refresh(new_table.focus)

        # Update the filter indicator using enum's __str__ method
        filter_indicator = self.query_one("#filter-indicator", Static)
        filter_name = self.current_filter.label
        filter_indicator.update(f"Filter: {filter_name}")

        # Log about the filter change
        logger.debug(f"Filter changed to: {filter_name}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle table selection."""
        if self.current_table is None or self.table_pl_grouped is None:
            msg = "Attempted to refresh table with no data loaded."
            raise RuntimeError(msg)
        row_index = event.cursor_row

        if 0 <= row_index < self.current_table.height:
            row = self.current_table.row(row_index, named=True)

            logger.info(
                f"Row selected: index={row_index} Row group key={row['Group Key']} ",
            )

            filtered = self.table_pl_grouped.filter(pl.col("Group Key") == row["Group Key"])

            if len(filtered) > 1:
                msg = "table_pl_grouped[Group Key] must contain at most 1 row"
                raise ValueError(msg)

            territory_table: str | None = filtered["territory_table_primary"].item()
            geometry_primary: str | None = filtered["geometry_source_primary"].item()
            ndm_table: str | None = filtered["ndm_source"].list.first()[0]
            name_table: str | None = filtered["name"].list.first()[0]

            tables_set = TableSet(row["Group Key"], territory_table, geometry_primary, ndm_table, name_table)

            self.app.push_screen(
                DownloaderScreen(
                    row["Group Key"],
                    tables_set,
                ),
            )
        else:
            logger.warning(f"Invalid row index: {row_index}")


# TODO: With each line when the filter is on NDM/GEO (default value) include some sort of unicode icon in
# the rows in which Geometry, Name, and NDM are all present along with Territory.
