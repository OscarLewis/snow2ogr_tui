"""Snowflake login modal screen and helper functions.

This module provides utilities to locate and load the Snowflake
connections TOML file and a Textual ModalScreen implementation used
to present a Snowflake login UI within the TUI application.
"""

import asyncio
import platform
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from adbc_driver_manager import OperationalError
from adbc_driver_snowflake.dbapi import Connection, connect
from loguru import logger
from returns.result import Failure, ResultE, Success
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

if TYPE_CHECKING:
    from textual.timer import Timer

    from snow2ogr_tui.main import TuiApp


@dataclass(frozen=True)
class ConnectionInfo:
    """Immutable container for Snowflake connection details displayed in the UI."""

    user: str = ""
    account: str = ""
    database: str = ""
    warehouse: str = ""
    schema: str = ""
    role: str = ""


def get_snowflake_connections_path() -> Path:
    """Get the platform-specific path to Snowflake connections.toml file."""
    system = platform.system()

    if system == "Windows":
        # Windows: C:\Users\<username>\AppData\Local\Snowflake\connections.toml
        return Path.home() / "AppData" / "Local" / "Snowflake" / "connections.toml"
    # macOS and Linux: ~/.snowflake/connections.toml
    return Path.home() / ".snowflake" / "connections.toml"


def load_snowflake_connections() -> ResultE[dict[str, dict[str, str]]]:
    """Load Snowflake connections from TOML file.

    Returns:
        ResultE containing the connections dict, or an exception.

    """
    connections_path = get_snowflake_connections_path()

    if not connections_path.exists():
        return Failure(
            FileNotFoundError(
                f"Snowflake connections file not found at: {connections_path}",
            ),
        )

    try:
        with connections_path.open("rb") as f:
            return Success(tomllib.load(f))
    except (OSError, tomllib.TOMLDecodeError) as e:
        return Failure(e)


class SnowflakeConnected(Message):
    """Posted when a Snowflake connection has been established."""

    def __init__(self, connection: Connection) -> None:
        """Initialize the message with the established Snowflake connection.

        Args:
            connection: The active Snowflake Connection object.

        """
        super().__init__()
        self.connection = connection


class SFLoginScreen(ModalScreen):
    """Modal screen that displays Snowflake login information.

    The screen shows a simple container with a title and a brief
    keyboard hint, and triggers loading of the Snowflake
    connections file when mounted.
    """

    DEFAULT_CSS = """

    SFLoginScreen {
        align: center middle;
    }

    #login-container {
        width: 80;
        height: auto;
        max-height: 80%;
        min-height: 60%;
        border: $accent;
        background: $surface;
        padding: 1 2;
        layout: vertical;
    }

    #key-map {
        dock: bottom;
        padding: 0;
        margin-bottom:0;
    }

    """

    conn_info = reactive(ConnectionInfo())
    SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]  # noqa: RUF012 - Sorry for the mutable default values in a class attributes
    spinner_index = reactive(0)
    logged_in = reactive(False)  # noqa: FBT003 - Need this to be False by default

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "dismiss_login", "Close help"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    # TODO: Handle this error, happens when trying to login without the VPN on
    # adbc_driver_manager.OperationalError: IO: [Snowflake] 390422 (08004):
    # Incoming request with IP/Token 98.59.158.28 is not allowed to access Snowflake.
    # Contact your account administrator. For more information about this error, go to https://community.snowflake.com/s/ip-xxxxxxxxxxxx-is-not-allowed-to-access..
    # Vendor code: 390422. SQLSTATE: 08004

    def __init__(
        self,
        name: str | None = None,
        dom_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the login screen."""
        super().__init__(name=name, id=dom_id, classes=classes)
        self.sf_conn: Connection | None = None

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def compose(self) -> ComposeResult:
        """Compose the help screen with a container and markdown widget."""
        with Container(id="login-container"):
            yield Static("[b]Snowflake Login[/]", markup=True)
            yield Static("Logging in as user: ", id="user-name")
            yield Markdown("Press `escape` to close this window.", id="key-map")

    def watch_conn_info(self, conn_info: ConnectionInfo) -> None:
        """Update the displayed username when the connection details change."""
        text = Text("Logging in as user: ")
        text.append(conn_info.user, style="bold green")
        text.append(Text(" into account "))
        text.append(conn_info.account, style="bold blue")
        self.query_one("#user-name", Static).update(text)

    async def on_mount(self) -> None:
        """Start the Snowflake login process on window mount."""
        self.spinner_timer: Timer = self.set_interval(
            0.1,
            self._animate_spinner,
        )
        if self.sf_conn is None:
            result = load_snowflake_connections()
            first_conn = None
            match result:
                case Success(connections):
                    first_conn = self._fetch_first_connection(connections)
                case Failure(error):
                    logger.error(f"Failed to load config: {error}")

            # Update username in UI
            if first_conn and all(
                key in first_conn for key in ("user", "account", "database", "role", "schema", "warehouse")
            ):
                self.conn_info = replace(
                    self.conn_info,
                    user=first_conn["user"],
                    account=first_conn["account"],
                    database=first_conn["database"],
                    role=first_conn["role"],
                    schema=first_conn["schema"],
                    warehouse=first_conn["warehouse"],
                )
            logger.debug("Attempting to connect to Snowflake.")
            self.run_worker(self._login(), name="snowflake-login", exclusive=True)

    async def _login(self) -> None:
        try:
            conn = await self.connect_to_snowflake()
        except (OperationalError, RuntimeError):
            logger.exception("Failed to connect")
            return

        self.logged_in = True
        logger.debug("Posting SnowflakeConnected")
        self.post_message(SnowflakeConnected(conn))

        # Leave the success checkmark visible briefly.
        await asyncio.sleep(1)

        self.dismiss()

    async def connect_to_snowflake(self) -> Connection:
        """Connect to Snowflake, retrying once if the cached ID token is invalid."""
        db_kwargs = {
            "adbc.snowflake.sql.account": self.conn_info.account,
            "username": self.conn_info.user,
            "adbc.snowflake.sql.auth_type": "auth_ext_browser",
            "adbc.snowflake.sql.db": self.conn_info.database,
            "adbc.snowflake.sql.schema": self.conn_info.schema,
            "adbc.snowflake.sql.warehouse": self.conn_info.warehouse,
            "adbc.snowflake.sql.role": self.conn_info.role,
        }

        for attempt in range(2):
            try:
                return await asyncio.to_thread(connect, db_kwargs=db_kwargs)
            except OperationalError as e:
                if attempt == 0 and "390195" in str(e):
                    logger.info("Snowflake ID token expired. Retrying authentication...")
                    continue
                raise

        runtime_error_msg = "Snowflake Unreachable"
        raise RuntimeError(runtime_error_msg)

    def action_dismiss_login(self) -> None:
        """Dismiss the login screen."""
        self.dismiss()

    async def action_quit(self) -> None:
        """Delegate quit to the app."""
        await self.app.action_quit()

    def action_toggle_dark(self) -> None:
        """Delegate toggle dark mode to the app."""
        self.app.action_toggle_dark()

    def watch_spinner_index(self, _: int) -> None:
        """Refresh the login status text whenever the spinner advances."""
        self._update_login_text()

    def _animate_spinner(self) -> None:
        """Advance the spinner animation by one frame."""
        self.spinner_index = (self.spinner_index + 1) % len(self.SPINNER)

    def _fetch_first_connection(
        self,
        connections: dict[str, dict[str, str]],
    ) -> dict[str, str] | None:
        """Return the first Snowflake connection configuration, logging its name."""
        try:
            name, config = next(iter(connections.items()))
        except StopIteration:
            logger.warning("No Snowflake connections found in configuration")
        else:
            logger.debug(f"Snowflake Connection named '{name}': {config}")
            return config

    def _update_login_text(self) -> None:
        """Update the login status line with connection details and progress."""
        text = Text("Logging in as user: ")
        text.append(self.conn_info.user, style="bold green")
        text.append(" into account ")
        text.append(self.conn_info.account, style="bold blue")

        if not self.logged_in:
            text.append(f" {self.SPINNER[self.spinner_index]}", style="cyan")

        if self.logged_in:
            self.spinner_timer.stop()
            text.append(" ✓", style="bold green")
        text.append("\n")
        text.append(
            Text.assemble(
                "Database: ",
                Text(self.conn_info.database, style="green"),
            ),
        )
        text.append("\n")
        text.append(
            Text.assemble(
                "Schema: ",
                Text(self.conn_info.schema, style="green"),
            ),
        )
        text.append("\n")
        text.append(
            Text.assemble(
                "Role: ",
                Text(self.conn_info.role, style="green"),
            ),
        )
        text.append("\n")
        text.append(
            Text.assemble(
                "Warehouse: ",
                Text(self.conn_info.warehouse, style="green"),
            ),
        )
        if self.logged_in:
            text.append("\n")
            text.append("Logged In Successfully", style="bold green")
            self.query_one("#key-map", Markdown).update("Closing window in 1s...")
        self.query_one("#user-name", Static).update(text)
