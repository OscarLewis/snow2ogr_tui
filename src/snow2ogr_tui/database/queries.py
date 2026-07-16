"""Utilities for querying export records from the database as a Polars DataFrame.

The primary function provided is `fetch_exports_df`, which executes a SQL
select joining Exports with QueryPerformance (left outer join) and returns a
polars.DataFrame with appropriate dtype conversions for status and
timestamp columns.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from snow2ogr_tui.common.models import PackagedModel
from snow2ogr_tui.database.models import Exports, QueryDurationModelRegistry, QueryPerformance

if TYPE_CHECKING:
    from sqlalchemy.sql import Select


def fetch_exports_df(session: Session) -> pl.DataFrame:
    """Fetch export records from the database as a Polars DataFrame.

    Executes a SQL select joining Exports with QueryPerformance (left outer join)
    and returns a polars.DataFrame with appropriate dtype conversions for status
    and timestamp columns.

    Args:
        session: SQLAlchemy session for database access.

    Returns:
        A Polars DataFrame containing export records with QueryPerformance data.

    """
    stmt: Select[Any] = select(
        Exports.id,
        Exports.group_key,
        Exports.primary_table_name,
        Exports.geography_table,
        Exports.name_table,
        Exports.ndm_table,
        Exports.fetch_timestamp,
        Exports.output_path,
        Exports.sf_query_ids,
        Exports.sf_database,
        Exports.sf_schema,
        Exports.sf_data_timestamp,
        Exports.status,
        QueryPerformance.rows_fetched,
        QueryPerformance.columns_fetched,
        QueryPerformance.joined_tables,
        QueryPerformance.table_shapes,
        QueryPerformance.duration,
        QueryPerformance.predicted_duration,
    ).join(
        QueryPerformance,
        QueryPerformance.export_id == Exports.id,
        isouter=True,
    )

    df = pl.read_database(
        query=stmt,
        connection=session,
    )

    timestamp_cols = ["fetch_timestamp", "sf_data_timestamp"]
    for col in timestamp_cols:
        if col in df.columns:
            df = df.with_columns(
                pl.col(col).dt.replace_time_zone("UTC"),
            )

    return df


def package_model(model: QueryDurationModelRegistry) -> PackagedModel:
    """Package a QueryDurationModelRegistry into a PackagedModel.

    Converts the database model instance into the application-facing
    PackagedModel dataclass, ensuring the artifact_path is returned as a
    pathlib.Path instance.
    """
    return PackagedModel(
        id=model.id,
        created_at=model.created_at,
        name=model.model_name,
        type=model.model_type,
        parameters=model.parameters,
        metrics=model.metrics,
        artifact_path=Path(model.artifact_path),
    )
