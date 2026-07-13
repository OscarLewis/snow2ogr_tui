"""Downloader for exporting Territories data.

This module provides utilities to download and transform data into various formats
(GeoDataFrames, Polars DataFrames, Arrow tables) and to interact with Snowflake and SQL
metadata.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

import adbc_driver_snowflake.dbapi
import polars as pl
import polars_st as st
import polars_st.typing
from loguru import logger
from shapely import wkb as shapely_wkb
from shapely.errors import ShapelyError
from sqlalchemy import MetaData, Table, column, func, literal_column, select


def get_table_columns_with_types(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    table_name: str,
) -> list[tuple[str, str]]:
    """Get column names and their Snowflake data types from a table.

    Args:
        conn: ADBC Snowflake connection
        database: Database name
        schema: Schema name
        table_name: Table name (unqualified)

    Returns:
        List of (column_name, data_type) tuples in ordinal position order

    """
    query = f"""
    SELECT COLUMN_NAME, DATA_TYPE
    FROM {database.upper()}.INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{schema.upper()}'
      AND TABLE_NAME = '{table_name.upper()}'
    ORDER BY ORDINAL_POSITION
    """  # noqa: S608 I know this is literal SQL

    arrow_table = conn.execute(query).fetch_arrow_table()

    return [(row["COLUMN_NAME"], row["DATA_TYPE"]) for row in arrow_table.to_pylist()]


def fetch_table_to_polars(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    table_name: str,
    columns: list[str] | None = None,
    limit: int | None = None,
) -> pl.DataFrame:
    """Fetch a Snowflake table into Polars using Arrow ADBC with SQLAlchemy.

    Args:
        conn: ADBC Snowflake connection
        database: Database name
        schema: Schema name
        table_name: Table name (unqualified)
        columns: List of columns to select. If None, selects all.
        limit: Optional maximum number of rows to fetch.

    Returns:
        Polars DataFrame

    """
    metadata = MetaData(schema=schema)
    tbl = Table(table_name, metadata)

    if columns is None:
        stmt = select(literal_column("*")).select_from(tbl)
    else:
        cols = [column(col) for col in columns]
        stmt = select(*cols).select_from(tbl)

    if limit is not None:
        stmt = stmt.limit(limit)

    query = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    arrow_table = conn.execute(query).fetch_arrow_table()
    df: pl.DataFrame = pl.DataFrame(pl.from_arrow(arrow_table))

    if "FEATURE_ID" in df.columns:
        df = df.with_columns(pl.col("FEATURE_ID").cast(pl.Int64))

    return df


def geo_col(name: str) -> st.GeoExpr:
    """Create a typed Polars expression with polars-st spatial methods available."""
    return cast("st.GeoExpr", pl.col(name))


def fetch_geography_to_polars_st(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    table_name: str,
    geog_column_name: str,
    limit: int | None = None,
) -> tuple[st.GeoDataFrame, str]:
    """Fetch a Snowflake GEOGRAPHY column as WKB and convert to a polars-st GeoDataFrame.

    Args:
        conn: ADBC Snowflake connection
        database: Database name
        schema: Schema name
        table_name: Table name (unqualified)
        geog_column_name: Name of Snowflake GEOGRAPHY column
        limit: Optional maximum number of rows to fetch

    Returns:
        polars-st GeoDataFrame

    """
    metadata = MetaData(schema=schema)
    tbl = Table(table_name, metadata)

    stmt = select(
        literal_column("FEATURE_ID"),
        func.ST_ASWKB(column(geog_column_name)).label("WKB"),
    ).select_from(tbl)

    if limit is not None:
        stmt = stmt.limit(limit)

    query = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    arrow_table = conn.execute(query).fetch_arrow_table()

    df = pl.DataFrame(pl.from_arrow(arrow_table))

    if "FEATURE_ID" in df.columns:
        df = df.with_columns(pl.col("FEATURE_ID").cast(pl.Int64))

    geometry: st.GeoSeries = st.GeoSeries(df["WKB"], geometry_format="wkb").st.set_srid(
        4326,
    )

    geo_df: st.GeoDataFrame = st.GeoDataFrame(
        df.with_columns(geometry.alias("geometry")).drop("WKB"),
    )

    return geo_df, "geometry"


def is_hex_binary(value: str) -> bool:
    """Check whether a string is valid even-length hex."""
    if len(value) % 2:
        return False

    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    else:
        return True


def is_binary_string(value: str) -> bool:
    """Check whether a string likely contains raw binary data."""
    if not value:
        return False

    non_printable = sum(1 for char in value if ord(char) < 32 or ord(char) > 126)

    # Treat as binary if a meaningful portion is non-printable
    return non_printable > 0


def is_binary_column(table: pl.DataFrame, column_name: str) -> bool:
    """Check if a column contains possible binary string data by sampling values."""
    sample_size = min(5, len(table))
    if sample_size == 0:
        return False

    sample = table.sample(n=sample_size, seed=42)[column_name].to_list()

    checked_values = 0
    for val in sample:
        if val is None:
            continue

        checked_values += 1

        if not isinstance(val, str):
            return False

        if not (is_hex_binary(val) or is_binary_string(val)):
            return False

    return checked_values > 0


def is_valid_wkb_column(table: pl.DataFrame, column_name: str) -> bool:
    """Check if a column contains valid WKB data by sampling values."""
    sample_size = min(5, len(table))
    sample = table.sample(n=sample_size, seed=42)[column_name].to_list()

    valid_wkb_count = 0
    for val in sample:
        if val is None:
            continue
        try:
            shapely_wkb.loads(val)
            valid_wkb_count += 1
        except ShapelyError:
            pass

    return valid_wkb_count == len(sample)  # All sampled values must be valid WKB


def build_names_array(names_table: pl.DataFrame) -> pl.DataFrame:
    """Group names by FEATURE_ID and create a JSON array of name records.

    Parameters
    ----------
    names_table : pl.DataFrame
        Input names table containing FEATURE_ID and name attributes.

    Returns
    -------
    pl.DataFrame
        Columns:
            FEATURE_ID
            NAMES_ARRAY (JSON string)

    """
    names_clean = names_table.with_columns(
        pl.col("LANGUAGE").str.json_decode(pl.List(pl.String)).list.first().alias("LANGUAGE"),
    )

    return names_clean.group_by("FEATURE_ID").agg(
        pl.struct(
            "UNPARSED_FULL_NAME",
            "UNPARSED_NAME",
            "LANGUAGE",
            "NAME_TYPE",
            "CODE_TYPE",
            "NAME_RANK",
            "LOCALE_LIST_USE",
        )
        .implode()
        .struct.json_encode()
        .alias("NAMES_ARRAY"),
    )


def build_ndm_df(
    df: pl.DataFrame,
    json_cols=(
        "FEATURE_PROTO",
        "METADATA",
        "APPLE_EDITS",
    ),
    exclude_cols=(
        "FEATURE_PROTO",
        "METADATA",
        "APPLE_EDITS",
        "REPRESENTATIVE_POINT",
        "ISO_COUNTRY_CODE",
        "FEATURE_TYPE",
        "VENDOR_ID",
    ),
) -> pl.DataFrame:
    return df.select(
        "FEATURE_ID",
        *json_cols,
    ).join(
        df.select(
            pl.exclude(*exclude_cols),
        ).rename(
            {
                "LENGTH": "LENGTH_NDM",
                "AREA": "AREA_NDM",
                "PERIMETER": "PERIMETER_NDM",
            },
        ),
        on="FEATURE_ID",
        how="left",
    )


class GeometryType(str, Enum):
    WKB_BINARY = "WKB_BINARY"
    WKB_TEXT = "WKB_TEXT"
    SNOWFLAKE_GEOGRAPHY = "SNOWFLAKE_GEOGRAPHY"


class GeometrySource(str, Enum):
    SNOWFLAKE = "SNOWFLAKE"
    POLARS = "POLARS"


@dataclass
class GeometryDetectionResult:
    TYPE: GeometryType
    COLUMN: str
    SOURCE: GeometrySource

    def to_dict(self) -> dict[str, str]:
        return {
            "TYPE": self.TYPE.value,
            "COLUMN": self.COLUMN,
            "SOURCE": self.SOURCE.value,
        }


def prepare_spatial_table(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    table_name: str,
) -> tuple[pl.DataFrame, str | None]:
    """Fetch a table from Snowflake, automatically converting any geometry column into a representation suitable for SpatialData.

    Returns
    -------
    tuple[pl.DataFrame, str | None]
        (table, geometry_column_name)

    """
    columns: list[tuple[str, str]] = get_table_columns_with_types(
        conn,
        database,
        schema,
        table_name,
    )

    sample = fetch_table_to_polars(
        conn,
        database,
        schema,
        table_name=table_name,
        columns=[name for name, _ in columns],
        limit=50,
    )

    geom_res = detect_geometry(
        conn,
        database,
        schema,
        table=sample,
        table_name=table_name,
        column_names_and_types=columns,
    )

    if geom_res is None or geom_res.COLUMN in ("REPRESENTATIVE_POINT", "REP_POINT"):
        logger.debug(f"No geometry detected in '{table_name}'.")
        return (
            fetch_table_to_polars(
                conn,
                database,
                schema,
                table_name,
            ),
            None,
        )

    logger.debug(geom_res.to_dict())

    #
    # Snowflake GEOGRAPHY
    #
    if geom_res.TYPE == GeometryType.SNOWFLAKE_GEOGRAPHY:
        logger.debug(
            "Fetching geography as WKB from Snowflake before creating a Polars DataFrame...",
        )

        geom_wkb, geometry_column = fetch_geography_to_polars_st(
            conn,
            database,
            schema,
            table_name,
            geom_res.COLUMN,
        )

        attributes = fetch_table_to_polars(
            conn,
            database,
            schema,
            table_name,
            columns=[name for name, _ in columns if name != geom_res.COLUMN],
        )

        return (
            attributes.join(
                geom_wkb,
                on="FEATURE_ID",
                how="left",
            ),
            geometry_column,
        )

    #
    # Geometry already readable by Polars
    #
    if geom_res.SOURCE == GeometrySource.POLARS:
        logger.debug(
            "Safe to fetch the entire table into a Polars DataFrame before converting WKB.",
        )

        return (
            fetch_table_to_polars(
                conn,
                database,
                schema,
                table_name,
            ),
            geom_res.COLUMN,
        )

    #
    # Fallback
    #
    return (
        fetch_table_to_polars(
            conn,
            database,
            schema,
            table_name,
        ),
        None,
    )


def fetch_table_set(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    territory_table: str | None = None,
    geometry_table: str | None = None,
    name_table: str | None = None,
    ndm_table: str | None = None,
) -> tuple[pl.DataFrame | st.GeoDataFrame, bool]:
    """Fetch a territory dataset and optionally join names, geometry, and NDM.

    Returns a GeoDataFrame if any input table contains geometry.
    """
    if territory_table is None:
        raise ValueError("territory_table is required.")

    # Fetch the territory table.
    if geometry_table:
        logger.debug("Geometry table provided, skipping scan of territory table.")
        # Skip geometry detection since geometry will come from the separate table.
        result = fetch_table_to_polars(
            conn,
            database,
            schema,
            territory_table,
        )
        geometry_column = None
    else:
        # Territory table may contain geometry.
        result, geometry_column = prepare_spatial_table(
            conn,
            database,
            schema,
            territory_table,
        )

    # Join names.
    if name_table:
        logger.debug("Name table provided, joining aggregrate array to result.")
        names = build_names_array(
            fetch_table_to_polars(
                conn,
                database,
                schema,
                name_table,
            ),
        )

        result = result.join(
            names,
            on="FEATURE_ID",
            how="left",
        )

    # Join separate geometry table if provided.
    if geometry_table:
        geometry, geom_column = prepare_spatial_table(
            conn,
            database,
            schema,
            geometry_table,
        )

        result = result.join(
            geometry,
            on="FEATURE_ID",
            how="left",
            suffix="_GEOMETRY",
        )

        # Prefer the explicitly supplied geometry table.
        if geom_column is not None:
            geometry_column = geom_column

    # Join NDM table.
    if ndm_table:
        logger.debug("NDM table provided, joining table to result.")
        ndm = fetch_table_to_polars(
            conn,
            database,
            schema,
            ndm_table,
        )
        ndm_transformed = build_ndm_df(ndm)

        result = result.join(
            ndm_transformed,
            on="FEATURE_ID",
            how="left",
        )

    # Convert to a GeoDataFrame if geometry exists.
    if geometry_column is not None:
        if "geometry" in result.columns and geometry_column != "geometry":
            result = result.rename({"geometry": "previous_geometry"})

        if geometry_column != "geometry":
            result = result.rename({geometry_column: "geometry"})

        result = st.GeoDataFrame(
            result,
            geometry_name="geometry",
        )

    logger.debug(f"Result table shape: {result.shape}")

    return result, bool(geometry_column)


def detect_geometry(
    conn: adbc_driver_snowflake.dbapi.Connection,
    database: str,
    schema: str,
    table: pl.DataFrame,
    table_name: str,
    column_names_and_types: list[tuple[str, str]],
) -> GeometryDetectionResult | None:
    """Detect geometry columns and return their information."""

    def find_snowflake_schema_columns(
        predicate: Callable[[str, str], bool],
    ) -> list[tuple[str, str]]:
        return [(name, dtype) for name, dtype in column_names_and_types if predicate(name, dtype)]

    def find_polars_schema_columns(
        predicate: Callable[[str, pl.DataType], bool],
    ) -> list[tuple[str, pl.DataType]]:
        return [(name, dtype) for name, dtype in table.schema.items() if predicate(name, dtype)]

    # MATCHES HAPPEN IN A LIST OF PRIORITIES

    # 1. Snowflake GEOGRAPHY type
    for schema_column, _ in find_snowflake_schema_columns(
        lambda name, dtype: "GEOGRAPHY" in dtype.upper(),
    ):
        geom_table, geometry_column = fetch_geography_to_polars_st(
            conn,
            database,
            schema,
            table_name,
            schema_column,
            limit=10,
        )

        if is_valid_wkb_column(geom_table, "geometry"):
            return GeometryDetectionResult(
                TYPE=GeometryType.SNOWFLAKE_GEOGRAPHY,
                COLUMN=schema_column,
                SOURCE=GeometrySource.SNOWFLAKE,
            )

    # 2. Polars column name search
    for schema_column, _ in find_polars_schema_columns(
        lambda name, dtype: "WKB" in name.upper(),
    ):
        if is_valid_wkb_column(table, schema_column):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_BINARY,
                COLUMN=schema_column,
                SOURCE=GeometrySource.POLARS,
            )

    # 3. Snowflake column name search
    for schema_column, _ in find_snowflake_schema_columns(
        lambda name, dtype: "WKB" in name.upper(),
    ):
        if is_valid_wkb_column(table, schema_column):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_BINARY,
                COLUMN=schema_column,
                SOURCE=GeometrySource.SNOWFLAKE,
            )

    # 4. Polars Binary dtype search
    for schema_column, _ in find_polars_schema_columns(
        lambda name, dtype: dtype == pl.Binary,
    ):
        if is_valid_wkb_column(table, schema_column):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_BINARY,
                COLUMN=schema_column,
                SOURCE=GeometrySource.POLARS,
            )

    # 5. Snowflake BINARY type search
    for schema_column, _ in find_snowflake_schema_columns(
        lambda name, dtype: "BINARY" in dtype.upper(),
    ):
        if is_valid_wkb_column(table, schema_column):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_BINARY,
                COLUMN=schema_column,
                SOURCE=GeometrySource.SNOWFLAKE,
            )

    # 6. Polars String search
    for schema_column, _ in find_polars_schema_columns(
        lambda name, dtype: dtype == pl.String,
    ):
        if is_binary_column(table, schema_column) and is_valid_wkb_column(
            table,
            schema_column,
        ):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_TEXT,
                COLUMN=schema_column,
                SOURCE=GeometrySource.POLARS,
            )

    # 7. Snowflake TEXT search
    for schema_column, _ in find_snowflake_schema_columns(
        lambda name, dtype: "TEXT" in dtype.upper(),
    ):
        if is_binary_column(table, schema_column) and is_valid_wkb_column(
            table,
            schema_column,
        ):
            return GeometryDetectionResult(
                TYPE=GeometryType.WKB_TEXT,
                COLUMN=schema_column,
                SOURCE=GeometrySource.SNOWFLAKE,
            )

    return None


def write_geopackage(
    gdf: pl.DataFrame | st.GeoDataFrame,
    out_path: str | Path,
    geometry_column: str = "geometry",
) -> None:
    """Write a Polars/SpatialData GeoDataFrame to a GeoPackage.

    - Prints the SRID(s) of the geometry column.
    - Casts unsupported high-precision Decimal columns to supported types.
    - Renames the geometry column to ``geom`` for writing.
    - Overwrites any existing output file.
    """
    if geometry_column.lower() not in (name.lower() for name in gdf.schema.names()):
        raise ValueError(f"Geometry column '{geometry_column}' not found.")

    srids = gdf.select(geo_col(geometry_column).st.srid().alias("srid"))

    # File writing engine cannot handle Decimal columns with precision > 19.
    decimal_casts = [
        pl.col(col).cast(pl.Int64) if dtype.scale == 0 else pl.col(col).cast(pl.Decimal(19, 0))
        for col, dtype in gdf.schema.items()
        if isinstance(dtype, pl.Decimal)
    ]

    gdf = st.GeoDataFrame(
        gdf.with_columns(decimal_casts).rename({geometry_column: "geom"}),
        geometry_name="geom",
    )

    out_path = Path(out_path)
    if out_path.exists():
        out_path.unlink()

    gdf.st.write_file(out_path.as_posix(), geometry_name="geom")
    logger.debug(f"Wrote geopackage to `{out_path}`.")
