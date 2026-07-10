"""Downloader Screen Widget."""

from typing import ClassVar

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
        width: 20%;
        margin-top: 1;
    }

    #footer {
        margin-top: 1;
        color: $text-muted;
        content-align: center middle;
    }
    """

    def __init__(self, table_name: str) -> None:
        """Initialize the downloader screen."""
        super().__init__()
        self.table_name = table_name

    def compose(self) -> ComposeResult:
        """Compose the downloader screen."""
        with Container(id="downloader-container"), Vertical():
            yield Static("Downloader", id="title")

            yield Static("Selected Table", classes="heading")
            yield Static(self.table_name, id="selected-table")

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
                    flat=True,
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
