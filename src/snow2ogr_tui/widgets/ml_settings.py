"""ML Manager Window."""

from typing import TYPE_CHECKING, Any, ClassVar, cast

from loguru import logger
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from snow2ogr_tui.common.models import PackagedModel

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


class MLSettingsOpened(Message):
    """Posted when the ML settings page is opened."""

    def __init__(self) -> None:
        """Initialize the message/event."""
        super().__init__()


class TrainModelButtonPressed(Message):
    """Posted when the train model button is pressed."""

    def __init__(self) -> None:
        """Initialize the message/event."""
        super().__init__()


class MLSettingsScreen(ModalScreen):
    """A modal popup showing the MLSettingsScreen."""

    DEFAULT_CSS = """
    MLSettingsScreen {
        align: center middle;
    }

    #manager-container {
        width: 80;
        height: 100;
        max-height: 90%;
        max-width: 120;
        border: $accent;
        background: $surface;
        padding: 1 2;
    }

    #title {
        color: $text-accent;
        margin: 1 0 2 0;
        text-align: center;
        width: 100%;
        height: auto;
    }

    #model-info {
        margin-top: 1;
        height: auto;
    }

    #training-records {
        margin-bottom: 1;
    }

    #button-div {
        margin: 1;
    }

    #train-model-button.-style-default:focus {
        text-style: bold !important;
    }
    """

    # TODO: Refactor so screen updates when a new model has been trained and loaded

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,m", "dismiss_ml_manager", "Close ML Settings"),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        """Initialize the ML Settings screen."""
        super().__init__()

    def on_mount(self) -> None:
        """On mount start testing parameter values."""
        self.tui_app.ml_manager.start_tuning()
        self.refresh_model_info()
        self.watch(
            self.tui_app.ml_manager,
            "model_registry_entry",
            self._model_registry_changed,
        )

    def compose(self) -> ComposeResult:
        """Compose the help screen with a container and markdown widget."""
        with Container(id="manager-container"):
            yield Static(Text("Machine Learning Settings", "bold"), id="title")

            yield Static(
                content=Text(
                    "Train a new model based on all completed exports recorded locally. "
                    "This model is used to estimate export durations for future downloads.",
                ),
            )
            with Container(id="model-info"):
                yield Static(id="training-records")
                yield Static(id="current-model")
                yield Static(id="model-metrics")
            with Center(id="button-div"):
                yield Button(
                    "Train Model",
                    id="train-model-button",
                    variant="warning",
                )

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "train-model-button":
            self.tui_app.ml_manager.post_message(TrainModelButtonPressed())

    def action_dismiss_ml_manager(self) -> None:
        """Dismiss the MLSettingsScreen screen."""
        self.dismiss()

    def action_toggle_dark(self) -> None:
        """Delegate toggle dark mode to the app."""
        self.app.action_toggle_dark()

    async def action_quit(self) -> None:
        """Delegate quit to the app."""
        await self.app.action_quit()

    def _model_registry_changed(self, _model_info: PackagedModel) -> None:
        logger.debug(f"Refershed model info presented to user: {_model_info}")
        self.refresh_model_info()

    def refresh_model_info(self) -> None:
        """Refresh the displayed model information."""
        self.query_one("#training-records", Static).update(
            Text.assemble(
                "Number of records to train on: ",
                Text(str(self.tui_app.ml_manager.training_record_count), style="bold"),
            ),
        )

        current = self.query_one("#current-model", Static)
        metrics = self.query_one("#model-metrics", Static)

        if (entry := self.tui_app.ml_manager.model_registry_entry) is None:
            current.update("")
            metrics.update("")
            return

        current.update(
            Text.assemble(
                "Current Model ID: ",
                Text(str(entry.id), style="bold"),
            ),
        )

        if entry.metrics:
            m = entry.metrics
            metrics.update(
                Text.assemble(
                    Text("Number of records the loaded model is trained on: "),
                    Text(str(m["record_count"]), style="bold"),
                    "\n",
                    Text("MAE (Mean Absolute Error) in Seconds: : "),
                    Text(f"{m['mae_seconds']:.5f}s", style="bold"),
                    "\n",
                    Text("K-folds: "),
                    Text(str(m["folds"]), style="bold"),
                ),
            )
