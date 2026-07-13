"""SQLAlchemy ORM models for snow2ogr export tracking.

Defines ExportStatus enum, a custom PathType for storing pathlib.Path
objects, and ORM models Exports and QueryPerformance used to record
export metadata and query performance details.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Interval,
    String,
    TypeDecorator,
    func,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class ExportStatus(StrEnum):
    """Enumeration of possible export statuses.

    Inherits from ``str`` so members compare equal to their string
    values and serialize cleanly (e.g. to JSON or as SQL enum values).

    Attributes:
        IN_PROGRESS: The export has started but has not yet finished.
        COMPLETED: The export finished successfully.
        FAILED: The export was attempted but raised an error.
        MISSING: The expected export output could not be found.
        UNKNOWN: The export status has not been determined.

    """

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    MISSING = "missing"
    UNKNOWN = "unknown"


# Store and retrieves Paths and strings
class PathType(TypeDecorator):
    """SQLAlchemy column type for transparently persisting ``pathlib.Path`` objects.

    Values are stored in the database as strings (via the underlying
    ``String`` impl) and are converted back into ``Path`` objects when
    loaded, so ORM attributes using this type can be worked with as
    ``Path`` instances in application code.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Path | str | None, dialect) -> str | None:  # noqa: ANN001, ARG002 - I know we don't type or use dialect right now
        """Convert a value to a string before it is bound to a query.

        Args:
            value: The value being persisted, expected to be a
                ``pathlib.Path``, a string, or ``None``.
            dialect: The SQLAlchemy dialect in use (unused).

        Returns:
            The string representation of ``value``, or ``None`` if
            ``value`` is ``None``.

        """
        if value is None:
            return None
        return str(value)

    def process_result_value(
        self,
        value: Path | str | None,
        dialect,  # noqa: ANN001, ARG002 - I know we don't type or use dialect right now
    ) -> Path | None:
        """Convert a stored string value back into a ``pathlib.Path``.

        Args:
            value: The raw string value fetched from the database, or
                ``None``.
            dialect: The SQLAlchemy dialect in use (unused).

        Returns:
            A ``pathlib.Path`` built from ``value``, or ``None`` if
            ``value`` is ``None``.

        """
        if value is None:
            return None
        return Path(value)


class Base(DeclarativeBase):
    """Declarative base class shared by all ORM models in this module."""


# Base exports table
class Exports(Base):
    """ORM model for the ``exports`` table.

    Records metadata about a single export run, including the source
    Snowflake tables/queries involved, where the exported data was
    written, and the current status of the export. Each row may have an
    associated :class:`QueryPerformance` row capturing timing and size
    metrics for the underlying query. All timestamps are saved as UTC.

    Attributes:
        id: Primary key.
        group_key: Common name key of the table set being exported.
        primary_table_name: Name of the main table being exported.
        geography_table: Name of the associated geography table, if any.
        name_table: Name of the associated name/lookup table, if any.
        ndm_table: Name of the associated NDM table, if any.
        sf_query_ids: List of Snowflake query IDs used to produce the export.
        sf_database: Snowflake database the data was queried from.
        sf_schema: Snowflake schema the data was queried from.
        sf_data_timestamp: Timestamp of the source data in Snowflake.
        fetch_timestamp: When the export record was created; defaults to
            the database server's current time.
        output_path: Filesystem path where the export output was written.
        status: Current :class:`ExportStatus` of the export.
        query_performance: One-to-one related :class:`QueryPerformance`
            row with performance details for this export, if recorded.

    """

    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_key: Mapped[str] = mapped_column(String(100))
    primary_table_name: Mapped[str] = mapped_column(String(100))
    geography_table: Mapped[str] = mapped_column(String(100), nullable=True)
    name_table: Mapped[str] = mapped_column(String(100), nullable=True)
    ndm_table: Mapped[str] = mapped_column(String(100), nullable=True)
    sf_query_ids: Mapped[list[str]] = mapped_column(JSON, nullable=True)
    sf_database: Mapped[str] = mapped_column(String(100), nullable=True)
    sf_schema: Mapped[str] = mapped_column(String(100), nullable=True)
    sf_data_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    fetch_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    output_path: Mapped[Path | None] = mapped_column(
        PathType(500),
        nullable=True,
    )

    status: Mapped[ExportStatus] = mapped_column(
        SQLEnum(ExportStatus),
        default=ExportStatus.UNKNOWN,
        nullable=False,
    )

    query_performance: Mapped["QueryPerformance | None"] = relationship(
        back_populates="export",
        uselist=False,
        cascade="all, delete-orphan",
    )


class QueryDurationModelRegistry(Base):
    """Stores metadata about trained query duration models."""

    __tablename__ = "query_duration_models"

    id: Mapped[int] = mapped_column(primary_key=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now(UTC),
        nullable=False,
    )

    model_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    parameters: Mapped[dict[str, int | float | str]] = mapped_column(
        JSON,
        nullable=False,
    )

    metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    artifact_path: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    query_predictions: Mapped[list["QueryPerformance"]] = relationship(
        back_populates="prediction_model",
    )


class QueryPerformance(Base):
    """ORM model for the ``query_performance`` table.

    Captures performance metrics for the query behind a single
    :class:`Exports` row, such as how many rows/columns were fetched,
    how long the query took, and how that compared to a predicted
    duration.

    Attributes:
        id: Primary key.
        export_id: Foreign key to the related :class:`Exports` row.
            Unique, since each export has at most one performance record.
        rows_fetched: Number of rows returned by the query.
        columns_fetched: Number of columns returned by the query.
        duration: Actual wall-clock duration of the query.
        predicted_duration: Predicted duration of the query, if a
            prediction model was used.
        predicted_method: Name/identifier of the method used to predict
            ``predicted_duration``.
        is_spatial: Whether the query involved spatial data/operations.
        joined_tables: the role of each joined table *at the time this query ran*.
        table_shapes: the shape of each joined table *at the time this query ran*.
            Keys should match joined_tables soeach table name can be paired
            with its shape.
        export: The related :class:`Exports` row this performance record
            belongs to.

    """

    __tablename__ = "query_performance"

    id: Mapped[int] = mapped_column(primary_key=True)

    export_id: Mapped[int] = mapped_column(
        ForeignKey("exports.id"),
        unique=True,
        nullable=False,
    )
    rows_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    columns_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration: Mapped[timedelta | None] = mapped_column(
        Interval,
        nullable=True,
    )
    predicted_duration: Mapped[timedelta | None] = mapped_column(
        Interval,
        nullable=True,
    )
    predicted_method: Mapped[str] = mapped_column(String(100), nullable=True)
    is_spatial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_tables: Mapped[dict[str, str | None]] = mapped_column(JSON, nullable=True)
    table_shapes: Mapped[dict[str, tuple[int, int]]] = mapped_column(
        JSON,
        nullable=True,
    )
    export: Mapped["Exports"] = relationship(
        back_populates="query_performance",
    )

    prediction_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("query_duration_models.id"),
        nullable=True,
    )

    prediction_model: Mapped["QueryDurationModelRegistry | None"] = relationship(
        back_populates="query_predictions",
    )
