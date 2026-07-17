"""Snowflake Tables Tab with table-specific bindings."""

from typing import TYPE_CHECKING, ClassVar, cast

from adbc_driver_snowflake.dbapi import Connection
from loguru import logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer

from snow2ogr_tui.widgets.data_table import VimDataTable

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


class DataTableTab(Container):
    """Tab containing Snowflake tables with table-specific bindings."""

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def __init__(
        self,
        name: str | None = None,
        container_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the DataTableTab."""
        super().__init__(name=name, id=container_id, classes=classes)

    @property
    def sf_connection(self) -> Connection | None:
        """Return the application's current Snowflake connection."""
        return self.tui_app.sf_conn

    def compose(self) -> ComposeResult:
        """Compose the tab."""
        yield VimDataTable(cursor_type="row", id="vim-data-table")
        yield Footer()
