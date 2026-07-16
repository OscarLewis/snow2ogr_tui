"""Machine Learning manager for snow2ogr."""

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Self, cast

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from textual import work
from textual.reactive import reactive
from textual.widget import Widget
from textual.worker import Worker, WorkerState

from snow2ogr_tui.common.models import ExportDownloadStatus, PackagedModel
from snow2ogr_tui.database import Exports, QueryPerformance
from snow2ogr_tui.database.ml import QueryDurationModel, evaluate_duration_model_kfold, tune_ridge_alpha
from snow2ogr_tui.database.models import QueryDurationModelRegistry
from snow2ogr_tui.database.queries import package_model
from snow2ogr_tui.widgets.ml_settings import TrainModelButtonPressed

if TYPE_CHECKING:
    from types import CoroutineType

    from snow2ogr_tui.main import TuiApp


class MLManager(Widget):
    """Invisible widget that owns all machine learning model interactions."""

    DEFAULT_CSS = """
    MLManager {
        display: none;
    }
    """

    ridge_tunings = reactive[dict[str, int | float]](default={})
    model = reactive[QueryDurationModel | None](None)
    model_registry_entry = reactive[PackagedModel | None](None)
    _metrics = reactive[dict[str, float | list[float]] | None](None)

    def __init__(self, name: str | None = None, dom_id: str | None = None, classes: str | None = None) -> None:
        """Create a new ML manager instance."""
        super().__init__(name=name, id=dom_id, classes=classes)
        self._tuning_complete: bool = False
        self._model_loaded: bool = False
        self._tuning_worker: Worker[CoroutineType[Any, Any, dict[str, int | float]] | dict[str, int | float]] | None = (
            None
        )
        self._training_worker: Worker[CoroutineType[Any, Any, None] | None] | None = None
        self.completed_exports: list[QueryPerformance] | None = None

    def on_mount(self) -> None:
        """Set up ML model on mount."""
        # Fetch completed export QueryPerformances
        self.completed_exports = self._fetch_training_records()
        logger.debug(f"Records avaliable for ML training: {len(self.completed_exports)}")

        latest_model = self._fetch_latest_model()
        if latest_model:
            model = QueryDurationModel.load(latest_model.artifact_path)
            self.model = model
            self._model_loaded = True
            self.model_registry_entry = latest_model
            logger.debug(f"Loaded model id {latest_model.id} found at path {latest_model.artifact_path.as_posix()}")

    @property
    def tui_app(self) -> "TuiApp":
        """Return the parent TuiApp instance for this widget.

        This casts self.app to the concrete TuiApp type so callers get proper
        typing information when accessing application-level attributes.
        """
        return cast("TuiApp", self.app)

    @property
    def sessionlocal(self) -> sessionmaker[Session]:
        """Return the application's current Snowflake connection."""
        return self.tui_app.sessionlocal

    @property
    def metrics(self) -> dict[str, float | list[float]]:
        """Return the evaluation metrics for the currently loaded model."""
        if self._metrics is None:
            msg = "Model metrics have not been computed."
            raise RuntimeError(msg)
        return self._metrics

    def predict(self, record: QueryPerformance) -> timedelta:
        """Predicts the estimated duration of a export for a given record."""
        if self.model is None:
            msg = "Attempted to predict without a loaded model"
            raise RuntimeError(msg)
        return self.model.predict(record)

    def save_model(self, out_path: Path) -> None:
        """Save the model to the filesystem for later loading and packaging."""
        if self.model is None:
            logger.warning("Attemtpted to save an unloaded model.")
            return
        self.model.save(out_path)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        match event.worker:
            case self._tuning_worker:
                self._handle_tuning_worker(event)
            case self._training_worker:
                self._handle_training_worker(event)
            case _:
                return

    def _fetch_latest_model(self) -> PackagedModel | None:
        """Fetch the most recently created packaged model from the database."""
        with self.sessionlocal() as session:
            model = session.query(QueryDurationModelRegistry).order_by(QueryDurationModelRegistry.id.desc()).first()
            return None if model is None else package_model(model)

    def _fetch_existing_models(self) -> list[PackagedModel]:
        """Fetch persisted query duration model registry records from the database.

        Returns:
            list[QueryDurationModelRegistry]: All registry records stored in the DB.
        #

        """
        with self.sessionlocal() as session:
            models: list[QueryDurationModelRegistry] = session.query(QueryDurationModelRegistry).all()
            return [package_model(model) for model in models]

    def watch_ridge_tunings(
        self,
        tunings: dict[str, int | float] | None,
    ) -> None:
        """Handle updates to the computed ridge regression tunings."""
        if tunings is None:
            return
        if not tunings:  # Tunings computed but no values were produced (empty dict)
            return
        logger.debug(f"Best tunings: {tunings}")

    def watch_model(self, model: QueryDurationModel | None) -> None:
        """Handle updates to the trained query duration model."""
        if model is None:
            return
        logger.debug(f"Query duration model ready: {model.regressor}")

    def on_train_model_button_pressed(self, _message: TrainModelButtonPressed) -> None:
        """Handle when the 'Train Model' button is pressed."""
        logger.debug("Train model button clicked.")
        self._training_worker = self._train_ridge_model()

    def start_tuning(self) -> None:
        """Begin alpha tuning for the ridge regression model."""
        logger.debug("Stating alpha tuning for ML model on completed exports.")
        self._tuning_worker = self._tune_ridge_alpha(self.completed_exports)

    @work(exclusive=True)
    async def _train_ridge_model(self) -> None:
        """Train the ridge regression model using the tuned alpha.

        If ridge tunings have been computed, train a QueryDurationModel
        with the best alpha and store it on self.model.
        """
        if not self.ridge_tunings:
            # There should be tunings by this point but if not, we can generate them now.
            self._tuning_worker = self._tune_ridge_alpha(self.completed_exports)
            await self._tuning_worker.wait()

        if self.ridge_tunings and self.completed_exports:
            self.model = QueryDurationModel.train(
                self.completed_exports,
                alpha=float(self.ridge_tunings["best_alpha"]),
            )
            self._model_loaded = True
            self._metrics = evaluate_duration_model_kfold(
                self.completed_exports,
                float(self.ridge_tunings["best_alpha"]),
            )
            parameters = {
                "alpha": float(self.ridge_tunings["best_alpha"]),
            }
            logger.debug(f"Trained model metrics: {self._metrics}")
            logger.debug("Saving model...")
            model_name = f"ExportDurationRidge_{datetime.now():%Y%m%d_%H%M%S_%f}"
            model_out_path = Path("models") / Path(model_name).with_suffix(".joblib")
            logger.debug(isinstance(parameters, dict))
            with self.sessionlocal() as session:
                model_record = QueryDurationModelRegistry(
                    model_type="ridge",
                    model_name=model_name,
                    parameters=parameters,
                    metrics=self._metrics,
                    artifact_path=model_out_path.as_posix(),
                )
                session.add(model_record)
                session.commit()
                session.refresh(model_record)
                self.model_registry_entry = package_model(model_record)
            self.save_model(model_out_path)

    def _handle_training_worker(self, event: Worker.StateChanged) -> None:
        """Handle state changes for the model training worker."""
        if self._model_loaded:
            return
        match event.worker.state:
            case WorkerState.SUCCESS:
                self._model_loaded = True

            case WorkerState.ERROR:
                self._model_loaded = False
                logger.exception(
                    "Failed to train model",
                    exc_info=event.worker.error,
                )

            case _:
                pass

    def _handle_tuning_worker(self, event: Worker.StateChanged) -> None:
        """Handle state changes for the ridge tuning worker."""
        if self._tuning_complete:
            return

        match event.worker.state:
            case WorkerState.SUCCESS:
                self._tuning_complete = True

                if event.worker.result is None:
                    msg = "ML tuning worker result should never be None."
                    raise ValueError(msg)

                tunings: dict[str, int | float] = event.worker.result
                self.ridge_tunings = tunings

            case WorkerState.ERROR:
                self._tuning_complete = True
                logger.exception(
                    "Failed to tune ridge alpha",
                    exc_info=event.worker.error,
                )

            case _:
                pass

    @work(exclusive=True)
    async def _tune_ridge_alpha(self, training_records: list[QueryPerformance]) -> dict[str, int | float]:
        return tune_ridge_alpha(
            training_records,
        )

    def _fetch_training_records(self) -> list[QueryPerformance]:
        """Fetch completed records from the database."""
        with self.sessionlocal() as session:
            completed_exports: list[QueryPerformance] = (
                session.query(QueryPerformance)
                .join(QueryPerformance.export)
                .filter(
                    Exports.status == ExportDownloadStatus.COMPLETED,
                    QueryPerformance.joined_tables.isnot(None),
                    QueryPerformance.columns_fetched.isnot(None),
                    QueryPerformance.rows_fetched.isnot(None),
                    QueryPerformance.table_shapes.isnot(None),
                    QueryPerformance.duration.isnot(None),
                )
                .all()
            )
        return completed_exports

    @property
    def training_record_count(self) -> int:
        """Number of completed records available for training."""
        return self._fetch_count_training_record()

    def _fetch_count_training_record(self) -> int:
        """Return the number of completed records available for training."""
        with self.sessionlocal() as session:
            return (
                session.query(QueryPerformance)
                .join(QueryPerformance.export)
                .filter(
                    Exports.status == ExportDownloadStatus.COMPLETED,
                    QueryPerformance.joined_tables.isnot(None),
                    QueryPerformance.columns_fetched.isnot(None),
                    QueryPerformance.rows_fetched.isnot(None),
                    QueryPerformance.table_shapes.isnot(None),
                    QueryPerformance.duration.isnot(None),
                )
                .count()
            )
