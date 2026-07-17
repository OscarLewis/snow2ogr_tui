"""Poker boss of the Snowflake tables in schema dataframe."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, NamedTuple, cast

import polars as pl
from adbc_driver_manager import DatabaseError, OperationalError, ProgrammingError
from adbc_driver_snowflake.dbapi import Connection
from loguru import logger
from returns.result import Failure, ResultE, Success
from rich.text import Text
from textual import work
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from snow2ogr_tui.common import TableSet
from snow2ogr_tui.common.models import FilterType
from snow2ogr_tui.pipelines.group_tables import group_territory_tables, preprocess_table_metadata
from snow2ogr_tui.pipelines.list_tables import list_tables
from snow2ogr_tui.widgets import VimDataTable
from snow2ogr_tui.widgets.data_table import CommandLine, TableRowSelected
from snow2ogr_tui.widgets.downloader_screen import DownloaderScreen

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


COLUMN_NAMES = ("Table Name", "Creation Date")


class SnowflakeTablesinSchemaLoaded(Message):
    """Posted when table data has been successfully loaded."""

    def __init__(self) -> None:
        """Initialize the message/event."""
        super().__init__()


class TableSearchToggled(Message):
    """Posted when user enters the table search mode by pressing '/'."""

    def __init__(self) -> None:
        """Initialize the message/event."""
        super().__init__()


class FilterToggled(Message):
    """Posted when the table filter should be toggled."""

    def __init__(self, filter_type: FilterType | None = None) -> None:
        """Initialize the message with the new filter type.

        Args:
            filter_type: The filter to apply (FilterType.NDMGEO or None for no filter).

        """
        super().__init__()

        self.filter_type = filter_type


class DataFrameManager(Widget):
    """Invisible widget that owns the main data table backend."""

    DEFAULT_CSS = """
    DataFrameManager {
        display: none;
    }
    """

    # Was the initial table load from Snowflake completed successfully?
    table_loaded: reactive[bool] = reactive(False)  # noqa: FBT003 - I am intentionally setting this to default to False
    current_table_revision: reactive[int] = reactive(0)  # Track any changes to the dataframe
    current_filter: reactive[FilterType] = reactive(FilterType.NDMGEO)  # Track current filter state
    search_open: reactive[bool] = reactive(False)  # noqa: FBT003 - I am intentionally setting this to default to False

    def __init__(self, name: str | None = None, dom_id: str | None = None, classes: str | None = None) -> None:
        """Create a new dataframe manager instance."""
        super().__init__(name=name, id=dom_id, classes=classes)
        self.tables_extended = pl.DataFrame()
        self.tables_grouped = pl.DataFrame()

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    @property
    def sf_conn(self) -> Connection | None:
        """Return the application's current Snowflake connection."""
        return self.tui_app.sf_conn

    @property
    def current_dataframe(self) -> pl.DataFrame:
        """Return the dataframe backing the currently displayed table.

        Raises a RuntimeError if accessed before the initial Snowflake load
        has completed, since tables_extended/tables_grouped won't be populated yet.
        """
        if not self.table_loaded:
            msg = "current_dataframe accessed before Snowflake table data was loaded"
            raise RuntimeError(msg)

        return_df = self.tables_grouped if self.current_filter == FilterType.NDMGEO else self.tables_extended

        required_columns = {
            "territory_table_primary",
            "territory_table_creation_date",
            "Group Key",
        }

        missing = required_columns - set(return_df.columns)
        if missing:
            msg = f"Missing required columns: {', '.join(sorted(missing))}"
            raise RuntimeError(msg)

        return return_df

    @property
    def dataframe_shape(self) -> tuple[int, int]:
        """Return the shape of the current dataframe as (rows, columns)."""
        if not self.table_loaded:
            msg = "current_dataframe accessed before Snowflake table data was loaded"
            raise RuntimeError(msg)
        return self.current_dataframe.shape

    @property
    def current_dataframe_display(self) -> pl.DataFrame:
        """Return the a pretty version of the dataframe backing the currently displayed table.

        Raises a RuntimeError if accessed before the initial Snowflake load
        has completed, since tables_extended/tables_grouped won't be populated yet.
        """
        if not self.table_loaded:
            msg = "current_dataframe accessed before Snowflake table data was loaded"
            raise RuntimeError(msg)
        return (
            self.current_dataframe.select(
                pl.col("territory_table_primary"),
                pl.col("territory_table_creation_date").dt.strftime("%Y-%m-%d %H:%M:%S"),
            )
            .sort("territory_table_creation_date", descending=True)
            .rename({"territory_table_primary": COLUMN_NAMES[0], "territory_table_creation_date": COLUMN_NAMES[1]})
        )

    def on_filter_toggled(self, _: FilterToggled) -> None:
        """Handle filter toggle message and refresh the table.

        Cycle through filters: FilterType.NDMGEO -> FilterType.RAW -> FilterType.NDMGEO
        """
        if self.current_filter == FilterType.RAW:
            self.current_filter = FilterType.NDMGEO
        else:
            self.current_filter = FilterType.RAW
        logger.debug(f"There are {len(self.current_dataframe_display):,} records found in the current filter")
        # Update table revesion after filter changes
        self.current_table_revision += 1

    def on_mount(self) -> None:
        """Once application is loaded, initialize the DataFrame manager."""

    def fetch_data(self) -> None:
        """Fetch Snowflake table metadata asynchronously."""
        self._worker_load_data()

    def on_table_row_selected(self, message: TableRowSelected) -> None:
        """Handle selection of a table row and log the selected row."""
        row = self.current_dataframe_display.row(message.index, named=True)
        logger.debug(
            f"Row selected: index={message.index} - Table Name: {row['Table Name']} ",
        )
        table_set_selected = self._table_set_from_index(message.index)
        self.app.push_screen(
            DownloaderScreen(
                table_set_selected,
            ),
        )

    def _table_set_from_index(self, index: int) -> TableSet:
        """Return the TableSet for the selected table row index."""
        row = self.current_dataframe.row(index, named=True)
        group_key: str | None = row.get("Group Key")
        if group_key is None:
            msg = f"No 'Group Key' found in {row}"
            raise RuntimeError(msg)

        groups_filtered_to_key = self.tables_grouped.filter(pl.col("Group Key") == group_key)

        if len(groups_filtered_to_key) > 1:
            msg = "table_pl_grouped[Group Key] must contain at most 1 row"
            raise ValueError(msg)

        territory_table: str = groups_filtered_to_key["territory_table_primary"].item()
        geometry_primary: str | None = groups_filtered_to_key["geometry_source_primary"].item()
        ndm_table: str | None = groups_filtered_to_key["ndm_source"].list.first().item()
        name_table: str | None = groups_filtered_to_key["name"].list.first().item()
        result = TableSet(group_key, territory_table, geometry_primary, ndm_table, name_table)
        logger.debug(f"TablSet selected {result}")
        return result

    def on_table_search_toggled(self, _message: TableSearchToggled) -> None:
        """"""
        self.search_open = not self.search_open

    class TableLoadResult(NamedTuple):
        """Result of fetching a list of tables in Snowflake schema."""

        df_extended: pl.DataFrame
        df_grouped: pl.DataFrame
        load_sucess: bool

    @work(exclusive=True)
    async def _worker_load_data(self) -> ResultE[TableLoadResult]:
        """Load table metadata from Snowflake and prepare grouped DataFrames."""
        if self.sf_conn is None:
            return Failure(RuntimeError("Snowflake Connection is not loaded"))
        tables_result: list[tuple[str, datetime | None]] = []
        try:
            logger.debug("Attempting to list tables in Snowflake")
            self.schema = "TERRITORY_APP"
            self.database = "MAPS_DATA_SEMANTIC_DB"
            tables_result = await asyncio.to_thread(
                list_tables,
                self.sf_conn,
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
            tables_in_schema = pl.DataFrame(
                tables_result,
                schema=["Table Name", "Creation Date"],
                orient="row",
            )
            # Preprocess the metadata of each table to extract a group key and timestamp
            tables_extended = preprocess_table_metadata(tables_in_schema)
            # Group the records by {Group_Key: Territory_Table, Geometry_Table, Names_Table, NDM_Table}
            tables_grouped = group_territory_tables(tables_extended)

            # Save for Later
            # Rename columns and sort
            self.tables_extended = tables_extended.rename(
                {"Table Name": "territory_table_primary", "Creation Date": "territory_table_creation_date"},
            ).sort("territory_table_creation_date", descending=True)
            self.tables_grouped = tables_grouped.sort("territory_table_creation_date", descending=True)
            self.table_loaded = True
            logger.debug(f"tables_extended columns: {self.tables_extended.columns}")
            logger.debug(f"tables_grouped columns: {self.tables_grouped.columns}")
            # Post message that data has been loaded
            self.post_message(SnowflakeTablesinSchemaLoaded())
            logger.info(
                f"Successfully loaded {len(self.tables_extended):,} rows from SnowFlake"
                f"filtered into {len(self.tables_grouped):,} groups",
            )
        return Success(self.TableLoadResult(self.tables_extended, self.tables_grouped, self.table_loaded))
