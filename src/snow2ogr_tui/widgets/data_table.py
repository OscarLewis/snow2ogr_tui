"""Fast data table widget for the Snow2OGR with VIM keybinds for navigation."""

from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from loguru import logger
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, Middle, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, LoadingIndicator, Static
from textual_fastdatatable import DataTable

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


# Add this message class near the top of your file, after imports
class TableRowSelected(Message):
    """Posted when a row in the table has been selected."""

    def __init__(self, index: int) -> None:
        """Initialize the message/event with the indes of the selection."""
        super().__init__()

        self.index = index


class VimStyleTable(DataTable):
    """DataTable with Vim-style navigation bindings."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("j", "cursor_down", "Cursor down", show=False),
        Binding("k", "cursor_up", "Cursor up", show=False),
        Binding("h", "cursor_left", "Cursor left", show=False),
        Binding("l", "cursor_right", "Cursor right", show=False),
    ]


class CommandMode(StrEnum):
    """Enumeration of supported command-line modes for the table."""

    COMMAND = auto()
    SEARCH = auto()


class CommandPrompt(Static):
    """Prompt displayed before the command line."""

    mode = reactive(CommandMode.COMMAND)

    def render(self) -> Text:
        """Render the mode-specific prefix for the command input."""
        match self.mode:
            case CommandMode.SEARCH:
                return Text("/", "bold")
            case CommandMode.COMMAND:
                return Text(":", "bold")


class CommandLine(Input):
    """Command line input for table command mode."""

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def key_escape(self) -> None:
        """Handle when escape is pressed when CommandLine is focused for user input."""
        self.value = ""
        self.display = False
        self.app.query_one("#table-cmd-prompt", CommandPrompt).mode = CommandMode.COMMAND
        self.app.query_one("#table-cmd-prompt").display = False
        self.tui_app.df_manager.search_open = False
        self.app.query_one(VimStyleTable).focus()


class CommandMessage(Message):
    """Posted when a table command should be sent to the DataFrame Manager."""

    def __init__(self, mode: CommandMode, content: str) -> None:
        """Initialize the message/event with the indes of the selection."""
        super().__init__()

        self.mode = mode
        self.content = content


class VimDataTable(Container):
    """A container with a data table and loading indicator using Vim-style bindings."""

    # Explicitly configure the z-index layers via basic CSS
    DEFAULT_CSS = """
    VimDataTable {
        layers: base top;
    }

    VimDataTable #table-status-bar {
        layer: base;
        height: 1;
        dock: top;
        width: auto;
        padding: 0 1;
    }

    VimDataTable #filter-indicator {
        width: auto;
    }

    VimDataTable #record-count {
        width: 1fr;
        content-align: right middle;
    }

    VimDataTable .data-table {
        layer: base;
        height: 1fr;
    }

    VimDataTable #no-results {
        height: 1fr;
        width: auto;
        padding: 2 1 1 1;
        color: $warning;
    }

    VimDataTable #loading-indicator {
        width: 100%;
        height: 1;
    }

    VimDataTable #loading-overlay {
        layer: top;
        width: 100%;
        height: 100%;
        background: $background;
    }

    VimDataTable #loading-indicator {
        width: 100%;
        height: 1;
        align-horizontal: center;
    }

    VimDataTable #loading-text {
        width: auto;
        text-align: center;
        margin-bottom: 1;
    }

    VimDataTable #loading-overlay-content {
        width: auto;
        height: auto;
    }

    VimDataTable #table-cmd-container {
        dock: bottom;
        height: 1;
        padding: 0 2 0 1;
        background: $background;
    }

    VimDataTable #table-cmd-prompt {
        width: 2;
        content-align: center middle;
        color: $text;
        text-style: bold;
    }

    VimDataTable #table-cmd-input {
        width: 1fr;
        border: none;
        padding: 0;
        background: $background;
    }

    VimDataTable #table-cmd-input:focus {
        border: none;
        background: $background;
    }
    """

    # Was the initial table load from Snowflake completed successfully?
    table_loaded = reactive(False)  # noqa: FBT003 - I am intentionally setting this to default to False
    current_table_revision = reactive(0)

    def __init__(
        self,
        *args: Any,  # noqa: ANN401 - I know this shouldn't be 'Any' but it's fine, it's just going to the parent Class
        cursor_type: Literal["cell", "row", "column", "none"] = "row",
        **kwargs,
    ) -> None:
        """Initialize VimDataTable with DataTable parameters."""
        super().__init__(*args, **kwargs)
        self.cursor_type = cursor_type

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def on_mount(self) -> None:
        """Set up the table by watching DataFrameManager."""
        self.watch(self.tui_app.df_manager, "table_loaded", self._handle_table_loaded_change, init=False)
        self.watch(self.tui_app.df_manager, "current_table_revision", self._handle_table_rev_change, init=False)
        self.watch(self.tui_app.df_manager, "search_open", self._handle_search_open_close, init=False)

        # Hide the table command line
        self.query_one("#table-cmd-prompt", CommandPrompt).display = False
        self.query_one("#table-cmd-input", CommandLine).display = False

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle table selection."""
        row_index = event.cursor_row
        if 0 <= row_index < self.tui_app.df_manager.current_dataframe_display.height:
            self.tui_app.df_manager.post_message(TableRowSelected(row_index))

    def _handle_table_rev_change(self) -> None:
        """Handle updating the table when the current table revision changes."""
        logger.debug("'Current Table' Revision updated, refreshing table view")
        self._refresh_table_view()

    def _handle_table_loaded_change(self) -> None:
        """Handle updating the table when the DataFrame Manager loads the tables from SnowFlake."""
        logger.debug("Detected that tables are now loaded")
        grouped_parq_out = Path("tables_grouped.parquet")
        grouped_parq_out.unlink(missing_ok=True)
        self.tui_app.df_manager.current_dataframe.write_parquet(grouped_parq_out)
        self._refresh_table_view()

    def _handle_search_open_close(self) -> None:
        """Toggle the visibility and focus of the table search prompt and input.

        When df_manager.search_open is True the prompt and command input are
        displayed and the input is focused. When False they are hidden and the
        input is blurred.
        """
        prompt = self.query_one("#table-cmd-prompt", CommandPrompt)
        input_dom = self.query_one("#table-cmd-input", CommandLine)
        if self.tui_app.df_manager.search_open:
            prompt.mode = CommandMode.SEARCH
            input_dom.display = True
            prompt.display = True
            prompt.update(Text("/", style="bold"))
            self.call_after_refresh(input_dom.focus)
        if not self.tui_app.df_manager.search_open:
            prompt.mode = CommandMode.COMMAND
            input_dom.value = ""
            input_dom.blur()
            input_dom.display = False
            prompt.display = False

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle changes to the table command input."""
        mode = self.query_one("#table-cmd-prompt", CommandPrompt).mode

        if event.input.id == "table-cmd-input":
            self.tui_app.df_manager.post_message(CommandMessage(mode, event.value))

    def _refresh_table_view(self) -> None:
        """Refresh the displayed table when new data is available."""
        loading_overlay = self.query_one("#loading-overlay")
        loading_overlay.display = False
        # Unmount the old table
        old_table = self.query_one(VimStyleTable)
        no_results = self.query_one("#no-results", Static)

        if self.tui_app.df_manager.current_dataframe_display.height == 0:
            old_table.display = False
            no_results.display = True
            return

        old_table.remove()
        no_results.display = False

        new_table = VimStyleTable(
            data=self.tui_app.df_manager.current_dataframe_display,
            cursor_type=self.cursor_type,
            classes="data-table",
        )
        filter_indicator = self.query_one("#filter-indicator", Static)
        filter_indicator.update(
            Text.assemble(
                "Filter: ",
                Text(self.tui_app.df_manager.current_filter.label, "bold"),
            ),
        )
        record_count = self.query_one("#record-count", Static)
        record_count.update(
            Text.assemble(
                "Number of tables (filtered): ",
                Text(f"{(self.tui_app.df_manager.dataframe_shape[0]):,}", "bold"),
            ),
        )
        self.mount(new_table)
        new_table.display = True

    def compose(self) -> ComposeResult:
        """Create the layout with data table and loading indicator."""
        # Add filter indicator at the top
        with Horizontal(id="table-status-bar"):
            yield Static(
                Text.assemble(
                    "Filter: ",
                    Text(self.tui_app.df_manager.current_filter.label, "bold"),
                ),
                id="filter-indicator",
            )
            yield Static("Number of tables in filter: 0", id="record-count")
        with Horizontal(id="table-cmd-container"):
            yield CommandPrompt(id="table-cmd-prompt")
            yield CommandLine(id="table-cmd-input")
        yield VimStyleTable(cursor_type=self.cursor_type, classes="data-table")
        yield Static(Text("No matching tables found.", "bold"), id="no-results")
        with Container(id="loading-overlay"), Middle(), Center(), Vertical(id="loading-overlay-content"):
            yield Static("Fetching Snowflake tables...", id="loading-text")
            yield LoadingIndicator(id="loading-indicator")
