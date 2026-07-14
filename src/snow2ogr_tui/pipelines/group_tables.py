"""Pipeline functions for grouping Snowflake table metadata."""

import uuid

import polars as pl

DATE_PATTERN = r"(\d{8})"


def preprocess_table_metadata(df: pl.DataFrame) -> pl.DataFrame:
    """Extract metadata from Snowflake table names.

    Table must contain 'Table Name' and 'Creation Date' columns.
    """
    required_columns = {"Table Name", "Creation Date"}
    missing = required_columns - set(df.columns)
    if missing:
        msg = f"Missing required column(s): {', '.join(sorted(missing))}"
        raise ValueError(msg)

    df = df.with_columns(
        # Extract latest YYYYMMDD from the table name
        pl.col("Table Name").cast(pl.String).str.extract_all(DATE_PATTERN).list.max().alias("Date From Name"),
        # Group key (table family)
        pl.col("Table Name")
        .str.replace(r"_(TERRITORY_NAME|POSTCODE|TERRITORY|SOURCE_TABLE)", "")
        .str.replace(r"_(GEOMETRY_DATA|NDM_DATA)$", "")
        .alias("Group Key"),
        # Table classification
        pl.when(pl.col("Table Name").str.contains("_GEOMETRY_DATA"))
        .then(pl.lit("geometry_source"))
        .when(pl.col("Table Name").str.contains("_NDM_DATA"))
        .then(pl.lit("ndm_source"))
        .when(pl.col("Table Name").str.contains("_TERRITORY_NAME_"))
        .then(pl.lit("name"))
        .when(pl.col("Table Name").str.contains("_TERRITORY_"))
        .then(pl.lit("territory"))
        .otherwise(pl.lit("other"))
        .alias("Table Type"),
    )

    # Generate one UUID per unique Group Key so that each Group Key will be unique once persisted to a database
    unique_groups = df.select("Group Key").unique()
    group_uuids = {row["Group Key"]: str(uuid.uuid4()) for row in unique_groups.iter_rows(named=True)}
    # Map the UUID to each row
    uuid_df = pl.DataFrame(
        {
            "Group Key": list(group_uuids.keys()),
            "_uuid": list(group_uuids.values()),
        },
    )
    df = df.join(uuid_df, on="Group Key").with_columns(
        (pl.col("Group Key") + "_" + pl.col("_uuid")).alias("Group Key"),
    )
    return df.drop("_uuid")


def group_territory_tables(df: pl.DataFrame) -> pl.DataFrame:
    """Group territory-related tables by Group Key and derive primary tables."""
    expected_types = [
        "territory",
        "name",
        "geometry_source",
        "ndm_source",
        "other",
    ]

    # Equivalent of groupby + apply(list) + unstack(fill_value=[])
    grouped = (
        df.group_by(["Group Key", "Table Type"])
        .agg(pl.col("Table Name"))
        .pivot(
            values="Table Name",
            index="Group Key",
            on="Table Type",
        )
    )

    # Add any missing expected columns
    for col in expected_types:
        if col not in grouped.columns:
            grouped = grouped.with_columns(
                pl.lit([]).cast(pl.List(pl.String)).alias(col),
            )

    # Creation dates per group
    creation_dates = df.group_by("Group Key").agg(
        pl.col("Creation Date").alias("Creation_Dates"),
    )

    # Territory table creation date
    territory_creation_dates = (
        df.filter(pl.col("Table Type") == "territory")
        .group_by("Group Key")
        .agg(pl.col("Creation Date").first().alias("territory_table_creation_date"))
    )

    # Join metadata
    grouped = grouped.join(creation_dates, on="Group Key", how="left").join(
        territory_creation_dates,
        on="Group Key",
        how="left",
    )

    # Determine primary territory table
    grouped = grouped.with_columns(
        pl.col("territory").list.first().alias("territory_table_primary"),
    )

    for col in ["other", "geometry_source", "name", "ndm_source"]:
        grouped = grouped.with_columns(
            pl.when(pl.col("territory_table_primary").is_null())
            .then(pl.col(col).list.first())
            .otherwise(pl.col("territory_table_primary"))
            .alias("territory_table_primary"),
        )

    # Fallback creation date if no territory table exists
    grouped = grouped.with_columns(
        pl.when(pl.col("territory_table_creation_date").is_null())
        .then(pl.col("Creation_Dates").list.max())
        .otherwise(pl.col("territory_table_creation_date"))
        .alias("territory_table_creation_date"),
    )

    # Choose the preferred geometry source
    grouped = grouped.with_columns(
        pl.when(
            pl.col("geometry_source").list.eval(pl.element().str.contains("_SOURCE_TABLE_")).list.any(),
        )
        .then(
            pl.col("geometry_source")
            .list.eval(pl.element().filter(pl.element().str.contains("_SOURCE_TABLE_")))
            .list.first(),
        )
        .otherwise(pl.col("geometry_source").list.first())
        .alias("geometry_source_primary"),
    )

    # Final column ordering
    return grouped.select(
        [
            "Group Key",
            "Creation_Dates",
            "territory_table_creation_date",
            "territory_table_primary",
            "geometry_source_primary",
            *expected_types,
        ],
    )
