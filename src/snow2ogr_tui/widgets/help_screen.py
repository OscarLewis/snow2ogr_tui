"""Help Screen Widget."""

from typing import ClassVar

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
- `h/j/k/l` or `←/↑/↓/→` - Navigate the cursor

## Tips
- Press `Escape` to close this popup.
"""


class HelpScreen(ModalScreen):
    """A modal popup showing help text."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,question_mark", "dismiss_help", "Close help"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-container {
        width: 60%;
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

    def action_dismiss_help(self) -> None:
        """Dismiss the help screen."""
        self.dismiss()

    def on_click(self, event: Click) -> None:
        """Handle click events and dismiss when clicking outside the help box."""
        # optional: click outside the box to close
        if event.widget is self:
            self.dismiss()
