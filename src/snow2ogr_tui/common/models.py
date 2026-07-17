"""Common data models for snow2ogr_tui."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from pathlib import Path
from typing import Any, NamedTuple


class FilterType(StrEnum):
    """Filter types for table filtering."""

    NDMGEO = "ndmgeo"
    RAW = "raw"

    @property
    def label(self) -> str:
        """Return the display label for the filter type."""
        return "NDM/GEO" if self is FilterType.NDMGEO else self.value.upper()


class PackagedModel(NamedTuple):
    """Represents a packaged query duration model registry record."""

    id: int
    created_at: datetime
    name: str
    type: str
    parameters: dict[str, int | float | str]
    metrics: dict[str, Any] | None
    artifact_path: Path

    def __repr__(self) -> str:
        """Return the canonical string representation of this PackagedModel."""
        return (
            f"PackagedModel(\n"
            f"  id={self.id},\n"
            f"  created_at={self.created_at:%Y-%m-%d %H:%M:%S},\n"
            f"  name={self.name!r},\n"
            f"  type={self.type!r},\n"
            f"  parameters={self.parameters!r},\n"
            f"  metrics={self.metrics!r},\n"
            f"  artifact_path={self.artifact_path!r},\n"
            f")"
        )


class GeospatialOutputFormat(StrEnum):
    """Supported geospatial export formats."""

    SHAPEFILE = "shp"
    GEOPACKAGE = "gpkg"
    GEOJSON = "geojson"
    CSV = "csv"
    FLATGEOBUF = "fgb"
    GEOPARQUET = "parquet"
    KML = "kml"
    GML = "gml"
    DXF = "dxf"


@dataclass
class TableSet:
    """Data class for storing table references."""

    Group_Key: str
    Territory_Table: str
    Geometry_Table: str | None = None
    NDM_Table: str | None = None
    Name_Table: str | None = None


class ExportDownloadStatus(StrEnum):
    """Export workflow states used by the UI."""

    IDLE = auto()

    IN_PROGRESS = auto()

    MISSING = auto()
    UNKNOWN = auto()

    FETCHING_TABLES = auto()
    FETCHING_TERRITORY = auto()
    FETCHING_NAMES = auto()
    FETCHING_GEOMETRY = auto()
    CONVERTING_GEOMETRY = auto()
    FETCHING_NDM = auto()

    JOINING_TABLES = auto()

    EXPORTING_FILE = auto()
    FINALIZING = auto()

    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

    def __str__(self) -> str:
        """Return a human-readable text for this status."""
        return _EXPORT_STATUS_TEXT[self]

    def __repr__(self) -> str:
        """Return the canonical representation of this status."""
        return f"{type(self).__name__}({str(self)!r})"


_EXPORT_STATUS_TEXT: dict[ExportDownloadStatus, str] = {
    ExportDownloadStatus.IDLE: "Waiting to start",
    ExportDownloadStatus.MISSING: "Missing",
    ExportDownloadStatus.UNKNOWN: "Unknown",
    ExportDownloadStatus.IN_PROGRESS: "In progress",
    ExportDownloadStatus.FETCHING_TABLES: "Fetching tables",
    ExportDownloadStatus.FETCHING_TERRITORY: "Fetching territory table",
    ExportDownloadStatus.FETCHING_NAMES: "Fetching names",
    ExportDownloadStatus.FETCHING_GEOMETRY: "Fetching geometry",
    ExportDownloadStatus.FETCHING_NDM: "Fetching NDM data",
    ExportDownloadStatus.JOINING_TABLES: "Joining datasets",
    ExportDownloadStatus.CONVERTING_GEOMETRY: "Converting geometry",
    ExportDownloadStatus.EXPORTING_FILE: "Writing output file",
    ExportDownloadStatus.FINALIZING: "Finalizing export",
    ExportDownloadStatus.COMPLETED: "Export completed",
    ExportDownloadStatus.FAILED: "Export failed",
    ExportDownloadStatus.CANCELLED: "Export cancelled",
}
