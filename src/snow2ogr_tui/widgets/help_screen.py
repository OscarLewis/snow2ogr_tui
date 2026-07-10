"""Help Screen Widget."""

from typing import ClassVar, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Markdown

HELP_TEXT = """\
# Help

## Keybindings
- `^q` — Quit
- `?` — Toggle this help screen
- `d` — Toggle dark mode
- `f` - Toggle the filter to show/hide the Name, Geometry_Data, and NDM_Data tables.
- `h/j/k/l` or `←/↑/↓/→` - Navigate the cursor

## Tips
- Press `Escape` to close this popup.
"""


class HelpScreen(ModalScreen):
    """A modal popup showing help text."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,question_mark", "dismiss_help", "Close help"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f", "toggle_table_filter", "Toggle Filter"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-container {
        width: 80%;
        height: auto;
        max-height: 80%;
        border: $accent;
        background: $surface;
        padding: 1 2;
    }

    HelpScreen MarkdownH1 {
        color: $text;
        text-style: bold;
        content-align: center middle;
    }

    HelpScreen MarkdownH2 {
        color: $text;
        text-style: bold underline;
    }

    HelpScreen MarkdownBullet {
       color: $accent-darken-2;
    }

    """

    def compose(self) -> ComposeResult:
        """Compose the help screen with a container and markdown widget."""
        with Container(id="help-container"):
            yield Markdown(HELP_TEXT)

    async def action_toggle_table_filter(self) -> None:
        """Toggle the table filter."""
        await self.app.run_action("toggle_table_filter")

    def action_dismiss_help(self) -> None:
        """Dismiss the help screen."""
        self.dismiss()

    def action_toggle_dark(self) -> None:
        """Delegate toggle dark mode to the app."""
        self.app.action_toggle_dark()

    async def action_quit(self) -> None:
        """Delegate quit to the app."""
        await self.app.action_quit()

    def on_click(self, event: Click) -> None:
        """Handle click events and dismiss when clicking outside the help box."""
        # optional: click outside the box to close
        if event.widget is self:
            self.dismiss()
