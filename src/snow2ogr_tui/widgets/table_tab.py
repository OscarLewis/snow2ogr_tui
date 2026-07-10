"""Snowflake Tables Tab with table-specific bindings."""

from typing import ClassVar

from loguru import logger
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer

from snow2ogr_tui.widgets.data_table import FilterToggled, VimDataTable
from snow2ogr_tui.widgets.help_screen import HelpScreen


class DataTableTab(Container):
    """Tab containing Snowflake tables with table-specific bindings."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f", "toggle_table_filter", "Toggle Filter"),
        Binding("d", "toggle_dark", "Dark Mode"),
        Binding("question_mark", "toggle_help", "Help"),
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

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.app.theme = "textual-dark" if self.app.theme == "textual-light" else "textual-light"

    def action_toggle_help(self) -> None:
        """Toggle Help Screen visibility."""
        # If help is already open, close it; otherwise open it
        if isinstance(self.app.screen, HelpScreen):
            self.app.pop_screen()
        else:
            self.app.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Quit the application."""
        await self.app.action_quit()
