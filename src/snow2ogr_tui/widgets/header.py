"""Header Widget."""

from textual.widgets import Static


class AppHeader(Static):
    """A simple header bar with just a title."""

    DEFAULT_CSS = """
    AppHeader {
        dock: top;
        width: 100%;
        height: 1;
        background: $background;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }
    """

    def __init__(self, title: str = "", **kwargs) -> None:
        """Initialize Header class."""
        super().__init__(title, **kwargs)
