"""Downloader Screen Widget."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static

from snow2ogr_tui.common.models import TableSet


class DownloadButtonPressed(Message):
    """Posted when the download button is pressed."""

    def __init__(self, table_set: TableSet) -> None:
        """Initialize the message/event with the loaded table data."""
        super().__init__()

        self.table_set = table_set


class DownloaderScreen(ModalScreen):
    """Modal screen displaying download progress for the selected table."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f", "toggle_table_filter", "Toggle Filter"),
    ]

    DEFAULT_CSS = """
    DownloaderScreen {
        align: center middle;
    }

    #downloader-container {
        width: 80;
        height: auto;
        max-width: 90;
        border: $accent;
        background: $surface;
        padding: 1 2;
    }

    #title {
        content-align: center middle;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    .heading {
        text-style: bold underline;
        color: $text;
        margin-top: 1;
    }

    #selected-table {
        color: $text-accent;
        margin-top: 1;
    }

    #current-step {
        color: $text;
    }

    ProgressBar {
        margin: 1 0;
    }

    #start-download-button {
        width: auto;
        margin-top: 1;
    }

    #start-download-button.-style-default:focus {
        text-style: bold !important;
    }

    #footer {
        margin-top: 1;
        color: $text-muted;
        content-align: center middle;
    }
    """
    group_key: str

    def __init__(self, group_key: str, table_set: TableSet) -> None:
        """Initialize the downloader screen."""
        super().__init__()

        self.Territory_Table = table_set.Territory_Table
        self.Geometry_Table = table_set.Geometry_Table
        self.NDM_Table = table_set.NDM_Table
        self.Names_Table = table_set.Name_Table
        self.table_set = table_set
        self.group_key = group_key

    def compose(self) -> ComposeResult:
        """Compose the downloader screen."""
        with Container(id="downloader-container"), Vertical():
            yield Static("Downloader", id="title")

            yield Static("Selected Table Set", classes="heading")
            yield Static(f"{self.Territory_Table}", id="selected-table")
            if self.Geometry_Table:
                yield Static(f"[bold]Geometry Table[/bold]: {self.Geometry_Table}", markup=True)
            if self.NDM_Table:
                yield Static(f"[bold]NDM Source Tables[/bold]: {self.NDM_Table}", markup=True)
            if self.Names_Table:
                yield Static(f"[bold]Name Source Tables[/bold]: {self.Names_Table}", markup=True)

            yield Static("Status", classes="heading")
            yield Static("Waiting to start...", id="current-step")

            yield ProgressBar(
                id="download-progress",
                total=100,
                show_eta=True,
            )

            with Center():
                yield Button(
                    "Start Download",
                    id="start-download-button",
                    variant="primary",
                )

            yield Static(
                "Press Esc to close",
                id="footer",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "start-download-button":
            self.post_message(DownloadButtonPressed(self.table_set))

    def action_close(self) -> None:
        """Close the downloader screen."""
        self.dismiss()

    def action_toggle_dark(self) -> None:
        """Toggle the application's dark mode."""
        self.app.action_toggle_dark()

    async def action_toggle_table_filter(self) -> None:
        """Toggle the table filter in the parent application."""
        await self.app.run_action("toggle_table_filter")

    async def action_quit(self) -> None:
        """Quit the application."""
        await self.app.action_quit()

    def on_click(self, event: Click) -> None:
        """Dismiss the modal when the background is clicked."""
        if event.widget is self:
            self.dismiss()
