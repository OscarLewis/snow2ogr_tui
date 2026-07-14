"""Downloads Tab with download-specific bindings."""

from typing import TYPE_CHECKING, ClassVar, cast

from loguru import logger
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
        Binding("ctrl+q", "quit", "Quit"),
        Binding("c", "clear_downloads", "Clear", show=True),
        Binding("d", "toggle_dark", "Dark Mode"),
        Binding("question_mark", "toggle_help", "Help"),
    ]

    DEFAULT_CSS = """
    DownloadsTab {
        width: 1fr;
        height: 1fr;
    }

    DownloadsTab > Static {
        height: 1fr;
        padding: 0 1;
        text-style: italic;
    }
    """

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def compose(self) -> ComposeResult:
        """Compose the tab."""
        yield Static("Downloads Tab Placeholder (WIP).", id="downloader-placeholder")
        yield Static(id="session-downloads")
        yield Footer()

    def action_clear_downloads(self) -> None:
        """Clear download history."""
        logger.info("Clear downloads action triggered")
        # TODO: Implement clear downloads functionality

    def action_toggle_dark(self) -> None:
        """Toggle dark mode."""
        self.app.theme = "textual-dark" if self.app.theme == "textual-light" else "textual-light"

    def action_toggle_help(self) -> None:
        """Toggle Help Screen visibility."""
        # If help is already open, close it; otherwise open it
        if isinstance(self.app.screen, HelpScreen):
            self.app.pop_screen()
        else:
            self.app.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Quit the application."""
        await self.app.action_quit()
