"""Snowflake Tables Tab with table-specific bindings."""

from typing import ClassVar

from loguru import logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer

from snow2ogr_tui.widgets.data_table import FilterToggled, VimDataTable


class DataTableTab(Container):
    """Tab containing Snowflake tables with table-specific bindings."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f", "toggle_table_filter", "Toggle Filter"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the tab."""
        yield VimDataTable(cursor_type="row", id="vim-data-table")
        yield Footer()

    def action_toggle_table_filter(self) -> None:
        """Toggle the table filter."""
        logger.info("Filter toggled")
        # Get the VimDataTable widget
        vim_data_table = self.query_one("#vim-data-table", VimDataTable)

        # Send the FilterToggled message to it
        vim_data_table.post_message(FilterToggled())
