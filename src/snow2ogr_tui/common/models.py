"""Common data models for snow2ogr_tui."""

from dataclasses import dataclass
from enum import StrEnum, auto


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

    Group_Key: str | None = None
    Territory_Table: str | None = None
    Geometry_Table: str | None = None
    NDM_Table: str | None = None
    Name_Table: str | None = None


class ExportDownloadStatus(StrEnum):
    """Export workflow states used by the UI."""

    IDLE = auto()

    FETCHING_TABLES = auto()
    FETCHING_TERRITORY = auto()
    FETCHING_NAMES = auto()
    FETCHING_GEOMETRY = auto()
    CONVERTING_GEOMETRY = auto()
    FETCHING_NDM = auto()

    JOINING_TABLES = auto()

    EXPORTING_FILE = auto()
    FINALIZING = auto()

    COMPLETE = auto()
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
    ExportDownloadStatus.FETCHING_TABLES: "Fetching tables",
    ExportDownloadStatus.FETCHING_TERRITORY: "Fetching territory table",
    ExportDownloadStatus.FETCHING_NAMES: "Fetching names",
    ExportDownloadStatus.FETCHING_GEOMETRY: "Fetching geometry",
    ExportDownloadStatus.FETCHING_NDM: "Fetching NDM data",
    ExportDownloadStatus.JOINING_TABLES: "Joining datasets",
    ExportDownloadStatus.CONVERTING_GEOMETRY: "Converting geometry",
    ExportDownloadStatus.EXPORTING_FILE: "Writing output file",
    ExportDownloadStatus.FINALIZING: "Finalizing export",
    ExportDownloadStatus.COMPLETE: "Export complete",
    ExportDownloadStatus.FAILED: "Export failed",
    ExportDownloadStatus.CANCELLED: "Export cancelled",
}
