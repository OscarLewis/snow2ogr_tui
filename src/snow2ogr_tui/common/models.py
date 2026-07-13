"""Common data models for snow2ogr_tui."""

from dataclasses import dataclass


@dataclass
class TableSet:
    """Data class for storing table references."""

    Group_Key: str | None = None
    Territory_Table: str | None = None
    Geometry_Table: str | None = None
    NDM_Table: str | None = None
    Name_Table: str | None = None
