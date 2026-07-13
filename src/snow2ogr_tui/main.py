"""Main function for creating a TUI App."""

from pathlib import Path
from typing import ClassVar

from adbc_driver_snowflake.dbapi import Connection
from loguru import logger
from platformdirs import user_log_dir
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from snow2ogr_tui.common import TableSet
from snow2ogr_tui.database import Exports, ExportStatus, init_db
from snow2ogr_tui.widgets import AppHeader, DataTableTab, DownloadsTab, VimDataTable
from snow2ogr_tui.widgets.data_table import TablesLoaded
from snow2ogr_tui.widgets.downloader_screen import DownloadButtonPressed
from snow2ogr_tui.widgets.help_screen import HelpScreen
from snow2ogr_tui.widgets.sf_login import SFLoginScreen, SnowflakeConnected

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

    # DB Set Up
    DB_Path = Path("snow2ogr.db")
    engine, sessionlocal = init_db(DB_Path, reset=False, echo=False)
    sf_conn: Connection | None = None

    BINDINGS: ClassVar[list[Binding]] = [
        # Global bindings - tab-specific bindings are defined in each tab class
        Binding("ctrl+q", "quit", "Quit"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("i", "toggle_login", "Login", show=False),
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

    def on_mount(self) -> None:
        """Show login screen on startup."""
        # This SFLoginScreen starts logging into Snowflake on mount and will reply with a SnowflakeConnected message.
        self.push_screen(SFLoginScreen())

    def on_tables_loaded(self, message: TablesLoaded) -> None:
        """Handle when tables are loaded."""
        logger.info(f"Tables loaded: {len(message.table_data)} tables")

    def on_snowflake_connected(self, message: SnowflakeConnected) -> None:
        """Store the Snowflake connection and fetch data."""
        self.sf_conn = message.connection
        logger.info("Connection to Snowflake established.")
        self.query_one(DataTableTab).query_one(VimDataTable).fetch_data()

    def action_toggle_login(self) -> None:
        """Toggle login screen."""
        self.push_screen(SFLoginScreen())

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"

    def on_download_button_pressed(self, message: DownloadButtonPressed) -> None:
        """Handle when the download button is pressed for a given table set."""
        logger.info(f"Download button clicked for table set {message.table_set}")
        self.data_analyst_worker(message.table_set)

    def action_toggle_help(self) -> None:
        """Toggle Help Screen visability."""
        # If help is already open, close it; otherwise open it
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen())

    @work()
    async def data_analyst_worker(self, table_set: TableSet) -> None:
        """Primary Data Worker, gets assigned to download a specific table set."""
        new_export_record = Exports(
            group_key=table_set.Group_Key,
            primary_table_name=table_set.Territory_Table,
            geography_table=table_set.Geometry_Table,
            name_table=table_set.Name_Table,
            ndm_table=table_set.NDM_Table,
            status=ExportStatus.UNKNOWN,
        )
        with self.sessionlocal() as session:
            session.add(new_export_record)
            session.commit()


def main() -> None:
    """Run Application."""
    app = TuiApp()
    logger.debug("Starting Snow2OGR TUI Application.")
    app.run()


if __name__ == "__main__":
    main()
