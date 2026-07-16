"""Downloader Screen Widget."""

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, cast

from loguru import logger
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Vertical
from textual.events import Click
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static

from snow2ogr_tui.common.models import ExportDownloadStatus, TableSet
from snow2ogr_tui.widgets.export_manager import ExportProgress

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


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
        max-height: 90%;
        max-width: 120;
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

    def __init__(self, group_key: str, table_set: TableSet) -> None:
        """Initialize the downloader screen."""
        super().__init__()
        self.group_key_export_status: ExportDownloadStatus = ExportDownloadStatus.UNKNOWN
        self.Territory_Table = table_set.Territory_Table
        self.Geometry_Table = table_set.Geometry_Table
        self.NDM_Table = table_set.NDM_Table
        self.Names_Table = table_set.Name_Table
        self.table_set = table_set
        self.group_key = group_key
        self._progress_timer = self.set_interval(0.2, self._update_progress_bar)
        self._progress: ExportProgress | None = None

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def compose(self) -> ComposeResult:
        """Compose the downloader screen."""
        with Container(id="downloader-container"), Vertical():
            yield Static("Export Tables", id="title")

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

    def on_mount(self) -> None:
        """Post a message to app when a DownloadScreen is opened."""
        self.set_interval(0.2, self._update_progress_bar)
        self.watch(self.tui_app.export_manager, "export_worker_revisions", self._export_revision_changed, init=False)

    def _export_revision_changed(self, old_value: dict[str, int]) -> None:
        """Handle changes in export worker revisions for this table set."""
        current_workers = list(old_value)
        matching_worker = next(
            (worker for worker in current_workers if worker.rsplit("_", 1)[0] == self.group_key),
            None,
        )
        if matching_worker:
            current_progress = self.tui_app.export_manager.export_workers.get(matching_worker)
            if current_progress is None:
                return
            self.update_status(current_progress)

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

    def _update_progress_bar(self) -> None:
        if (
            self._progress is None
            or self._progress.status == ExportDownloadStatus.COMPLETED
            or self._progress.estimated_duration is None
        ):
            return

        estimated = self._progress.estimated_duration.total_seconds()
        if estimated <= 0:
            return

        elapsed = (datetime.now(UTC) - self._progress.started_at).total_seconds()
        percent = min(elapsed / estimated * 100, 99)

        self.query_one("#download-progress", ProgressBar).update(progress=percent)

    def update_status(self, progress: ExportProgress) -> None:
        """Update the Export status presented to the user."""
        self._progress = progress
        self.group_key_export_status = progress.status
        logger.debug(f"Updating DownloaderScreen with {progress.status} for {self.group_key}")
        self._estimated_duration = progress.estimated_duration

        current_step = self.query_one("#current-step", Static)
        if self.group_key_export_status != ExportDownloadStatus.UNKNOWN:
            download_button = self.query_one("#start-download-button", Button)
            download_button.visible = False
        bar = self.query_one("#download-progress", ProgressBar)
        if progress.status == ExportDownloadStatus.COMPLETED:
            bar.update(progress=100)
            self._progress_timer.pause()
            current_step.update(
                Text.assemble(
                    str(progress.status),
                    " to ",
                    Text(progress.export_path.as_posix(), style="italic"),
                ),
            )
        else:
            self._update_progress_bar()

            current_step.update(Text.assemble(str(progress.status), Text("...")))
