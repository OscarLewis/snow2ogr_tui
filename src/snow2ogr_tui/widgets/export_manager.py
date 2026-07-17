"""Export Manager for Snow2OGR."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger
from platformdirs import user_downloads_path
from sqlalchemy.orm import Session, sessionmaker
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.worker import Worker

from snow2ogr_tui.common import TableSet
from snow2ogr_tui.common.models import ExportDownloadStatus, GeospatialOutputFormat
from snow2ogr_tui.database import Exports, QueryPerformance
from snow2ogr_tui.pipelines.downloader import fetch_metrics_tables, fetch_table_set, write_geopackage

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


@dataclass
class ExportProgress:
    """Track progress for a single export."""

    worker_id: str
    table_set: TableSet
    worker: Worker
    export_path: Path
    started_at: datetime
    status: ExportDownloadStatus
    estimated_duration: timedelta


class ExportDownloadStatusChanged(Message):
    """Notify listeners when an export worker changes status."""

    def __init__(self, worker_id: str, group_key: str) -> None:
        """Initialize the export status change message."""
        super().__init__()
        self.worker_id = worker_id
        self.group_key = group_key


class ExportManager(Widget):
    """Invisible widget that owns all export workers."""

    DEFAULT_CSS = """
    ExportManager {
        display: none;
    }
    """

    export_worker_revisions: reactive[dict[str, int]] = reactive({})

    def __init__(self, name: str | None = None, dom_id: str | None = None, classes: str | None = None) -> None:
        """Create a new export manager instance."""
        super().__init__(name=name, id=dom_id, classes=classes)
        self.export_workers: dict[str, ExportProgress] = {}

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

    def register_download(self, table_set: TableSet) -> str | None:
        """Register a new download and return worker ID."""
        if table_set.Territory_Table is None:
            msg = "Territory_Table cannot be None."
            raise ValueError(msg)
        worker_id = f"{table_set.Group_Key}_{len(self.export_workers)}"
        logger.debug(f"Worker {worker_id} assigned to download table set {table_set.Group_Key}")
        new_export_record = Exports(
            group_key=table_set.Group_Key,
            primary_table_name=table_set.Territory_Table,
            geography_table=table_set.Geometry_Table,
            name_table=table_set.Name_Table,
            ndm_table=table_set.NDM_Table,
            status=ExportDownloadStatus.UNKNOWN,
        )
        with self.sessionlocal() as session:
            session.add(new_export_record)
            logger.debug(f"Worker {worker_id} recording to database.")
            session.commit()

        export_path = user_downloads_path()

        out_file_path = export_path / Path(table_set.Territory_Table).with_suffix(".gpkg")

        export_worker = self.run_worker(
            self._export_table_set(
                worker_id,
                new_export_record.id,
                table_set,
                GeospatialOutputFormat.GEOPACKAGE,
                export_path,
            ),
            name=worker_id,
            exclusive=False,
            thread=True,
        )
        # TODO: Fix this from using two sources of truth for export path and extension.
        self.export_workers[worker_id] = ExportProgress(
            worker_id,
            table_set,
            export_worker,
            out_file_path,
            datetime.now(UTC),
            ExportDownloadStatus.IDLE,
            timedelta(seconds=0),
        )
        self.export_worker_revisions[worker_id] = 0
        return worker_id

    def _update_worker_revision(self, worker_id: str) -> int:
        """Increment and return the revision number for the given worker."""
        revisions = self.export_worker_revisions.copy()

        try:
            revisions[worker_id] += 1
        except KeyError as exc:
            msg = ("Attempted to update worker revision for a worker that could not be found by the manager.",)
            raise ValueError(msg) from exc

        self.export_worker_revisions = revisions
        return revisions[worker_id]

    def on_export_download_status_changed(
        self,
        event: ExportDownloadStatusChanged,
    ) -> None:
        """Handle export status change notifications from workers."""
        progress = self.export_workers[event.worker_id]
        revision = self._update_worker_revision(event.worker_id)
        logger.info(
            "[{}] {} - Revision: {}",
            event.worker_id,
            str(progress.status),
            revision,
        )

    def _set_worker_status(
        self,
        worker_id: str,
        status: ExportDownloadStatus,
    ) -> None:
        progress = self.export_workers[worker_id]

        # Only update and post if status actually changed
        if progress.status != status:
            progress.status = status
            if progress.table_set.Group_Key:
                self.post_message(
                    ExportDownloadStatusChanged(worker_id, group_key=progress.table_set.Group_Key),
                )

    async def _export_table_set(
        self,
        worker_id: str,
        export_record_id: int,
        table_set: TableSet,
        export_format: GeospatialOutputFormat,
        export_path: Path,
    ) -> None:
        """Export a table set to a given format and Path."""
        if table_set.Territory_Table is None:
            msg = "Territory_Table is required."
            raise ValueError(msg)
        if self.tui_app.sf_conn is None:
            msg = "Snowflake Connection is missing."
            raise RuntimeError(msg)
        self._set_worker_status(worker_id, ExportDownloadStatus.STARTING)

        out_file_path = export_path / Path(table_set.Territory_Table).with_suffix(".gpkg")
        logger.debug(f"Exporting {table_set.Group_Key} file to {out_file_path}")

        self.schema = "TERRITORY_APP"
        self.database = "MAPS_DATA_SEMANTIC_DB"
        self._set_worker_status(worker_id, ExportDownloadStatus.FETCHING_METRICS)

        # TODO: This call to SnowFlake is causing a hitch in performance
        # where the button to download doesn't go invisible for a second
        table_metrics = fetch_metrics_tables(
            self.tui_app.sf_conn,
            self.schema,
            self.database,
            table_set.Territory_Table,
            table_set.Geometry_Table,
            table_set.Name_Table,
            table_set.NDM_Table,
        )

        with self.sessionlocal() as session:
            export_record = session.query(Exports).filter(Exports.id == export_record_id).first()
            if export_record is None:
                msg = "No export records found in SQL filter for"
                " Export ID {export_record_id} / Group Key {table_set.Group_Key}"
                " when there should be at least one result"
                raise ValueError(msg)
            # Update the fetch_timestamp and status of the record for this export in the database
            export_record.fetch_timestamp = datetime.now(UTC)
            export_record.status = ExportDownloadStatus.IN_PROGRESS
            total_rows, total_col = map(sum, zip(*table_metrics.table_shapes, strict=True))

            query_performance = QueryPerformance(
                rows_fetched=total_rows,
                columns_fetched=total_col,
                is_spatial=table_metrics.is_spatial,
                table_shapes=table_metrics.table_shapes,
                joined_tables=table_metrics.joined_tables,
            )

            model_duration = self.tui_app.ml_manager.predict(
                query_performance,
            )
            self.export_workers[worker_id].estimated_duration = model_duration

            query_performance.predicted_duration = model_duration

            model_registry_entry = self.tui_app.ml_manager.model_registry_entry
            if model_registry_entry is None:
                msg = "predict() returned successfully but no model registry entry is loaded."
                raise RuntimeError(msg)
            query_performance.prediction_model_id = model_registry_entry.id

            export_record.query_performance = query_performance
            session.commit()

        logger.debug(f"Model predicted export duration of: {model_duration.total_seconds():2f}s")
        session.commit()

        # Start actually downloading the table
        try:
            self._set_worker_status(worker_id, ExportDownloadStatus.FETCHING_TABLES)
            fetch_result = fetch_table_set(
                self.tui_app.sf_conn,
                database=self.database,
                schema=self.schema,
                territory_table=table_set.Territory_Table,
                geometry_table=table_set.Geometry_Table,
                name_table=table_set.Name_Table,
                ndm_table=table_set.NDM_Table,
                status_callback=lambda status: self._set_worker_status(worker_id, status),
            )
            df, is_spatial, geometry_column, table_shapes, joined_tables = fetch_result
            if is_spatial:
                logger.debug(
                    f"Geometry detected in column '{geometry_column}' for"
                    f" export {export_record_id} (group key: {table_set.Group_Key})",
                )
        except Exception:
            self._set_worker_status(worker_id, ExportDownloadStatus.FAILED)
            raise

        self._set_worker_status(worker_id, ExportDownloadStatus.EXPORTING_FILE)
        write_geopackage(df, out_file_path)
        with self.sessionlocal() as session:
            export_record = session.query(Exports).filter(Exports.id == export_record_id).first()
            if export_record is None:
                msg = "No export records found in SQL filter for"
                " Export ID {export_record_id} / Group Key {table_set.Group_Key}"
                " when there should be at least one result"
                raise ValueError(msg)
            export_record.export_timestamp = datetime.now(UTC)
            export_ts = export_record.export_timestamp.replace(tzinfo=UTC)
            fetch_ts = export_record.fetch_timestamp.replace(tzinfo=UTC)
            performance_duration = export_ts - fetch_ts
            query_perf = export_record.query_performance
            if query_perf:
                query_perf.duration = performance_duration
                query_perf.is_spatial = is_spatial

            logger.debug(
                f"Performance duration: {performance_duration.total_seconds():.2f}s",
            )
            export_record.status = ExportDownloadStatus.COMPLETED
            session.commit()
        self._set_worker_status(worker_id, ExportDownloadStatus.COMPLETED)
