"""Main function for creating a TUI App."""

from pathlib import Path
from typing import ClassVar

from loguru import logger
from platformdirs import user_log_dir  # pip install platformdirs
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, TabbedContent, TabPane

from snow2ogr_tui.widgets import AppHeader, HelpScreen, VimDataTable
from snow2ogr_tui.widgets.data_table import FilterToggled, TablesLoaded

# Remove loguru's default stderr sink (avoids fighting with Textual's terminal control)
logger.remove()

log_dir = Path(user_log_dir("snow2ogr_tui", "oscarlewis"))

log_dir.mkdir(parents=True, exist_ok=True)

logger.add(
    sink=log_dir / Path("app.log"),
    rotation="10 MB",
    retention="1 week",
    level="DEBUG",
    enqueue=True,  # safe for async/threaded apps
    backtrace=True,
    diagnose=True,
)


class TuiApp(App):
    """A Textual app to manage stopwatches."""

    ENABLE_COMMAND_PALETTE = False  # This may change later if I have better ideas for the palette.

    DEFAULT_CSS = """
    #main-tabs {
        height: 1fr;
    }

    TabbedContent > TabPane {
        height: 100%;
    }

    #downloader-placeholder {
        padding: 0 2;
        text-style: italic;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("d", "toggle_dark", description="Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f", "toggle_table_filter", "Toggle Filter"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield AppHeader("snow2ogr")

        with TabbedContent(id="main-tabs"):
            with TabPane("Snowflake Tables", id="data-table-tab"):
                yield VimDataTable(cursor_type="row", id="vim-data-table")  # ✅ Direct mount

            with TabPane("Downloads", id="downloads-tab"):
                yield Static("Downloads Tab Placeholder (WIP).", id="downloader-placeholder")  # ✅ Direct mount

        yield Footer()

    def on_tables_loaded(self, message: TablesLoaded) -> None:
        """Handle when tables are loaded."""
        logger.info(f"Tables loaded: {len(message.table_data)} tables")

    def action_toggle_table_filter(self) -> None:
        """Toggle the table filter."""
        # Implement your filter toggle logic here
        logger.info("Filter toggled")
        # Get the VimDataTable widget
        vim_data_table = self.query_one("#vim-data-table", VimDataTable)

        # Send the FilterToggled message to it
        vim_data_table.post_message(FilterToggled())

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def action_toggle_help(self) -> None:
        """Toggle Help Screen visability."""
        # If help is already open, close it; otherwise open it
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen())


def main() -> None:
    """Run Application."""
    app = TuiApp()
    logger.debug("Starting Snow2OGR TUI Application.")
    app.run()


if __name__ == "__main__":
    main()
