"""Main function for creating a TUI App."""

from pathlib import Path
from typing import ClassVar

from loguru import logger
from platformdirs import user_log_dir  # pip install platformdirs
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from snow2ogr_tui.widgets import AppHeader, DataTableTab, DownloadsTab, VimDataTable
from snow2ogr_tui.widgets.data_table import TablesLoaded, VimStyleTable
from snow2ogr_tui.widgets.downloader_screen import DownloadButtonPressed
from snow2ogr_tui.widgets.help_screen import HelpScreen

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
    """

    BINDINGS: ClassVar[list[Binding]] = [
        # Global bindings - tab-specific bindings are defined in each tab class
        Binding("ctrl+q", "quit", "Quit"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield AppHeader("snow2ogr")

        with TabbedContent(id="main-tabs"):
            with TabPane("Snowflake Tables", id="data-table-tab"):
                yield DataTableTab()

            with TabPane("Downloads", id="downloads-tab"):
                yield DownloadsTab()

    def on_tables_loaded(self, message: TablesLoaded) -> None:
        """Handle when tables are loaded."""
        logger.info(f"Tables loaded: {len(message.table_data)} tables")

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def on_download_button_pressed(self, message: DownloadButtonPressed) -> None:
        """Handle when the download button is pressed for a given table set."""
        logger.info(f"Download button clicked for table set {message.table_set}")

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
