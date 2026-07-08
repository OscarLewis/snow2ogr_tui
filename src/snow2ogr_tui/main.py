"""Main function for creating a TUI App."""

from pathlib import Path
from typing import ClassVar

from loguru import logger
from platformdirs import user_log_dir  # pip install platformdirs
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer

from snow2ogr_tui.widgets import AppHeader, HelpScreen, VimDataTable
from snow2ogr_tui.widgets.data_table import TablesLoaded

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

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("d", "toggle_dark", description="Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
        Binding("f", "toggle_table_filter", "Toggle Filter (NDM/Geo)"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield AppHeader("snow2ogr")
        # TODO: Actually load the data from snowflake here, show a message and a LoadingIndicator
        # https://textual.textualize.io/widgets/loading_indicator/
        yield VimDataTable(cursor_type="row")
        yield Footer()

    def on_tables_loaded(self, message: TablesLoaded) -> None:
        """Handle when tables are loaded."""
        logger.info(f"Tables loaded: {len(message.table_data)} tables")

    def action_toggle_table_filter(self) -> None:
        """Toggle the table filter."""
        # Implement your filter toggle logic here
        logger.info("Filter toggled")

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
    app.run()


if __name__ == "__main__":
    main()
