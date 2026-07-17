"""Downloads Tab with download-specific bindings."""

from typing import TYPE_CHECKING, ClassVar, cast

from loguru import logger
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Footer, Static

from snow2ogr_tui.widgets.help_screen import HelpScreen

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


class DownloadsTab(Container):
    """Tab containing download history with download-specific bindings."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("c", "clear_downloads", "Clear", show=True),
    ]

    DEFAULT_CSS = """
    DownloadsTab {
        width: 1fr;
        height: 1fr;
    }

    #downloads-container {
        height: 1fr;
        margin: 1 0 0 1;
    }
    """

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def on_mount(self) -> None:
        """Check for any downloads that are in progress."""
        self.watch(self.tui_app.export_manager, "export_worker_revisions", self._export_revision_changed, init=False)
        self.can_focus = False

    def compose(self) -> ComposeResult:
        """Compose the tab."""
        with Container(id="downloads-container"):
            yield Static(Text("Number of current Downloads: 0"), id="session-downloads")
        yield Footer()

    def _export_revision_changed(self) -> None:
        """Handle changes in export worker revisions."""
        self._report_current_downloads()

    def _report_current_downloads(self) -> None:
        """"""
        session_downloads = self.query_one("#session-downloads", Static)
        session_downloads.update(
            Text.assemble(Text("Number of current Downloads: "), str(len(self.tui_app.export_manager.export_workers))),
        )

    def action_clear_downloads(self) -> None:
        """Clear download history."""
        logger.info("Clear downloads action triggered")
        # TODO: Implement clear downloads functionality
