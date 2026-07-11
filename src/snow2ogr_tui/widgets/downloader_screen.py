"""Downloader Screen Widget."""

from typing import ClassVar

import polars as pl
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static


class DownloadButtonPressed(Message):
    """Posted when the download button is pressed."""


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

    #status {
        color: $text;
    }

    #current-step {
        color: $text-muted;
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

    def __init__(self, group_key: str, group_info: pl.DataFrame) -> None:
        """Initialize the downloader screen."""
        super().__init__()
        self.table_name = group_info.select(pl.col("territory_table_primary")).item()
        self.group_info = group_info
        self.gorup_key = group_key
        self.geometry_primary: str | None = self.group_info["geometry_source_primary"].item()
        self.ndm_table: str | None = self.group_info["ndm_source"].list.first()[0]
        self.name_table: str | None = self.group_info["name"].list.first()[0]

    def compose(self) -> ComposeResult:
        """Compose the downloader screen."""
        with Container(id="downloader-container"), Vertical():
            yield Static("Downloader", id="title")

            yield Static("Selected Table Set", classes="heading")
            yield Static(f"{self.table_name}", id="selected-table")
            if self.geometry_primary:
                yield Static(f"[bold]Geometry Table[/bold]: {self.geometry_primary}", markup=True)
            if self.ndm_table:
                yield Static(f"[bold]NDM Source Tabls[/bold]: {self.ndm_table}", markup=True)
            if self.name_table:
                yield Static(f"[bold]Name Source Tabls[/bold]: {self.name_table}", markup=True)

            yield Static("Status", classes="heading")
            yield Static("Waiting to start...", id="status")

            yield ProgressBar(
                id="download-progress",
                total=100,
                show_eta=True,
            )

            yield Static("", id="current-step")

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
            self.post_message(DownloadButtonPressed())

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
