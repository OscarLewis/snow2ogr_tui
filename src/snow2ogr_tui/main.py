"""Main function for creating a TUI App."""

# ruff: noqa: ERA001 - I know there's commented out code right now
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from loguru import logger
from platformdirs import user_log_dir
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from snow2ogr_tui.database import init_db
from snow2ogr_tui.widgets import AppHeader, DataTableTab, DownloadsTab, VimDataTable
from snow2ogr_tui.widgets.downloader_screen import DownloadButtonPressed
from snow2ogr_tui.widgets.export_manager import ExportManager
from snow2ogr_tui.widgets.help_screen import HelpScreen
from snow2ogr_tui.widgets.ml_manager import MLManager
from snow2ogr_tui.widgets.sf_login import SFLoginScreen, SnowflakeConnected
from snow2ogr_tui.widgets.table_manager import (
    DataFrameManager,
    FilterToggled,
    SnowflakeTablesinSchemaLoaded,
    TableSearchToggled,
)

if TYPE_CHECKING:
    from adbc_driver_snowflake.dbapi import Connection

# Remove loguru's default stderr sink (avoids fighting with Textual's terminal control)
logger.remove()

# log_dir = Path(user_log_dir("snow2ogr_tui", "oscarlewis"))
log_dir = Path("logs")

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

    # TODO: Switch to installing screens instead of creating and destroying them each time I use one

    def __init__(
        self,
        db_path: Path | str = Path("snow2ogr.db"),
        *,
        reset_db: bool = False,
        echo_sql: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the TUI application and its database/engine.

        Args:
            db_path: Path to the SQLite database file.
            reset_db: If True, reset the database schema (delete all rows).
            echo_sql: If True, enable SQL echoing for debugging.
            **kwargs: Additional keyword arguments forwarded to the base App constructor.

        """
        super().__init__(**kwargs)

        self.db_path = Path(db_path)

        self.engine, self.sessionlocal = init_db(
            self.db_path,
            reset=reset_db,
            echo=echo_sql,
        )

        self.sf_conn: Connection | None = None
        self.export_manager: ExportManager = ExportManager(dom_id="export-manager")
        self.ml_manager: MLManager = MLManager(dom_id="ml-manager")
        self.df_manager: DataFrameManager = DataFrameManager(dom_id="df_manager")

    BINDINGS: ClassVar[list[Binding]] = [
        # Global bindings - tab-specific bindings are defined in each tab class
        Binding("f", "toggle_table_filter", "Filter"),
        Binding("d", "toggle_dark", "Dark Mode"),
        Binding("/", "toggle_table_search", "Search"),
        Binding("i", "toggle_login", "Login", show=False),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        # First thing is to add the invisible ExportManager that lives in the background of all things
        yield self.export_manager
        yield self.ml_manager
        yield self.df_manager
        yield AppHeader("snow2ogr")
        with TabbedContent(id="main-tabs"):
            with TabPane("Snowflake Tables", id="data-table-tab"):
                yield DataTableTab()

            with TabPane("Downloads", id="downloads-tab"):
                yield DownloadsTab()

    def on_mount(self) -> None:
        """Show login screen on startup."""
        # This SFLoginScreen starts logging into Snowflake on mount and will reply with a SnowflakeConnected message.
        self.push_screen(SFLoginScreen())

    def on_tables_loaded(self, message: SnowflakeTablesinSchemaLoaded) -> None:
        """Handle when tables are loaded."""

    def on_snowflake_connected(self, message: SnowflakeConnected) -> None:
        """Store the Snowflake connection and fetch data once loaded."""
        self.sf_conn = message.connection
        logger.info("Connection to Snowflake established.")
        # self.query_one(DataTableTab).query_one(VimDataTable).fetch_data()
        self.df_manager.fetch_data()

    def action_toggle_login(self) -> None:
        """Toggle login screen."""
        self.push_screen(SFLoginScreen())

    def action_toggle_table_search(self) -> None:
        """Toggle table search."""
        self.df_manager.post_message(TableSearchToggled())

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def on_download_button_pressed(self, message: DownloadButtonPressed) -> None:
        """Handle when the download button is pressed for a given table set."""
        logger.info(f"Download button clicked for table set {message.table_set}")
        self.export_manager.register_download(table_set=message.table_set)

    def action_toggle_help(self) -> None:
        """Toggle Help Screen visability."""
        # If help is already open, close it; otherwise open it
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen())

    def action_toggle_table_filter(self) -> None:
        """Toggle the table filter."""
        # Get the VimDataTable widget
        vim_data_table = self.query_one("#vim-data-table", VimDataTable)

        # Send the FilterToggled message to it
        vim_data_table.post_message(FilterToggled())
        self.df_manager.post_message(FilterToggled())


def main() -> None:
    """Run Application."""
    app = TuiApp()
    logger.info("Starting Snow2OGR TUI Application.")
    app.run()


if __name__ == "__main__":
    main()
