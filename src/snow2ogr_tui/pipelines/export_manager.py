"""Export Manager for Snow2OGR."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger
from platformdirs import user_downloads_path
from sqlalchemy.orm import Session, sessionmaker
from textual.message import Message
from textual.widget import Widget
from textual.worker import Worker

from snow2ogr_tui.common import TableSet
from snow2ogr_tui.common.models import ExportDownloadStatus, GeospatialOutputFormat
from snow2ogr_tui.database import Exports, ExportStatus, QueryPerformance
from snow2ogr_tui.pipelines.downloader import fetch_table_set, write_geopackage

if TYPE_CHECKING:
    from snow2ogr_tui.main import TuiApp


@dataclass
class ExportProgress:
    """Track progress for a single export."""

    worker_id: str
    table_set: TableSet
    worker: Worker
    export_path: Path
    status: ExportDownloadStatus


# TODO: Change this to ExportProgress
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

    def __init__(self, name: str | None = None, dom_id: str | None = None, classes: str | None = None) -> None:
        """Create a new manager instance."""
        super().__init__(name=name, id=dom_id, classes=classes)
        self.export_workers: dict[str, ExportProgress] = {}

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
            status=ExportStatus.UNKNOWN,
        )
        with self.sessionlocal() as session:
            session.add(new_export_record)
            logger.debug(f"Worker {worker_id} recording to database.")
            session.commit()

        # TODO: Register a new Worker object assigned to export that table_set
        export_path = user_downloads_path()

        out_file_path = export_path / Path(table_set.Territory_Table).with_suffix(".gpkg")

        export_worker = self.run_worker(
            self._export_table_set(worker_id, table_set, GeospatialOutputFormat.GEOPACKAGE, export_path),
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
            ExportDownloadStatus.IDLE,
        )
        return worker_id

    def on_export_download_status_changed(
        self,
        event: ExportDownloadStatusChanged,
    ) -> None:
        """Handle export status change notifications from workers."""
        progress = self.export_workers[event.worker_id]
        logger.info(
            "[{}] {}",
            event.worker_id,
            str(progress.status),
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
        table_set: TableSet,
        export_format: GeospatialOutputFormat,
        export_path: Path,
    ) -> None:
        """Export a table set to a given format and Path."""
        if table_set.Territory_Table is None:
            msg = "Territory_Table is required."
            raise ValueError(msg)
        with self.sessionlocal() as session:
            export_record = session.query(Exports).filter(Exports.group_key == table_set.Group_Key).first()
            if export_record is None:
                msg = f"No export records found in SQL filter for group key {table_set.Group_Key}"
                " when there should be at least one result"
                raise ValueError(msg)
            export_record.fetch_timestamp = datetime.now(UTC)
            session.commit()

        self.schema = "TERRITORY_APP"
        self.database = "MAPS_DATA_SEMANTIC_DB"
        logger.debug(f"Exporting {table_set.Group_Key} file to {export_path} in format {export_format}.")
        out_file_path = export_path / Path(table_set.Territory_Table).with_suffix(".gpkg")
        if self.tui_app.sf_conn is None:
            msg_0 = "No Snowflake connection available."
            raise RuntimeError(msg_0)
        try:
            self._set_worker_status(worker_id, ExportDownloadStatus.FETCHING_TABLES)
            df, is_spatial = fetch_table_set(
                self.tui_app.sf_conn,
                database=self.database,
                schema=self.schema,
                territory_table=table_set.Territory_Table,
                geometry_table=table_set.Geometry_Table,
                name_table=table_set.Name_Table,
                ndm_table=table_set.NDM_Table,
                status_callback=lambda status: self._set_worker_status(worker_id, status),
            )
        except Exception:
            self._set_worker_status(worker_id, ExportDownloadStatus.FAILED)
            raise
        else:
            self._set_worker_status(worker_id, ExportDownloadStatus.EXPORTING_FILE)
            write_geopackage(df, out_file_path)
            with self.sessionlocal() as session:
                export_record = session.query(Exports).filter_by(group_key=table_set.Group_Key).first()
                if export_record is None:
                    msg = f"Expected an export record for group key {table_set.Group_Key!r}, but none was found."
                    raise ValueError(msg)
                export_record.export_timestamp = datetime.now(UTC)
                export_ts = export_record.export_timestamp.replace(tzinfo=UTC)
                fetch_ts = export_record.fetch_timestamp.replace(tzinfo=UTC)
                performance_duration = export_ts - fetch_ts
                logger.debug(f"Performance duration: {performance_duration.total_seconds():.2f}s")
                export_record.query_performance = QueryPerformance(duration=performance_duration, is_spatial=is_spatial)
                session.commit()
            self._set_worker_status(worker_id, ExportDownloadStatus.COMPLETE)
