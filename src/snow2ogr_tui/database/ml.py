"""Ridge regression query duration model.

This module defines the machine learning model used to estimate query
execution duration.

The duration model uses:
- log-transformed row and column counts
- row/column interaction features
- join count
- spatial query indicator
- joined table names encoded with MultiLabelBinarizer
- aggregate table shape information

The model trains on log-transformed duration values and returns predictions
as ``datetime.timedelta`` objects.
"""

from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import Ridge
from sklearn.metrics import make_scorer, mean_absolute_error
from sklearn.model_selection import (
    GridSearchCV,
    KFold,
    cross_val_predict,
)
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import MultiLabelBinarizer, StandardScaler

from snow2ogr_tui.database.models import QueryPerformance


def _table_shape_features(
    table_shapes: list[dict | None],
) -> np.ndarray:
    """Convert table shapes into numeric aggregate features.

    Returns:
        Array containing:
        - log total rows
        - log total columns
        - log total cells

    """
    features = []

    for shapes in table_shapes:
        rows = 0
        cols = 0

        if shapes:
            for shape in shapes.values():
                if shape:
                    rows += shape[0]
                    cols += shape[1]

        features.append(
            [
                np.log1p(rows),
                np.log1p(cols),
                np.log1p(rows * cols),
            ],
        )

    return np.asarray(features)


def _duration_features(
    df: Iterable[QueryPerformance],
) -> tuple[np.ndarray, list[list[str]], np.ndarray]:
    """Build feature matrices for query duration prediction."""
    records = list(df)

    numeric = []

    tables = []

    for row in records:
        joined_tables = [table for table in (row.joined_tables or {}).values() if table is not None]

        rows = row.rows_fetched or 0
        cols = row.columns_fetched or 0

        numeric.append(
            [
                np.log1p(rows),
                np.log1p(cols),
                np.log1p(rows * cols),
                len(joined_tables),
                int(row.is_spatial),
            ],
        )

        tables.append(joined_tables)

    shapes = _table_shape_features(
        [row.table_shapes for row in records],
    )

    return (
        np.asarray(numeric),
        tables,
        shapes,
    )


def _build_training_matrix(
    records: Iterable[QueryPerformance],
) -> tuple[np.ndarray, np.ndarray, MultiLabelBinarizer]:
    """Build model training arrays."""
    records = [record for record in records if record.duration is not None]

    numeric, tables, shapes = _duration_features(records)

    table_encoder = MultiLabelBinarizer()

    table_features = table_encoder.fit_transform(
        tables,
    )

    x_array = np.hstack(
        [
            numeric,
            shapes,
            table_features,
        ],
    )

    # Train on log duration because query durations are heavily skewed.
    y_array = np.asarray(
        [np.log1p(record.duration.total_seconds()) for record in records if record.duration is not None],
    )

    return (
        x_array,
        y_array,
        table_encoder,
    )


class QueryDurationModel:
    """Ridge regression model for predicting database query execution duration.

    This model estimates query runtime using features derived from historical
    query performance records. It combines numeric query characteristics with
    encoded table metadata to predict execution time.

    The target variable is the log-transformed query duration in seconds.
    Predictions are inverse-transformed back into seconds and returned as a
    timedelta.

    The model consists of:
    - A scikit-learn regression pipeline containing feature scaling and a
      Ridge regression estimator.
    - A MultiLabelBinarizer used to encode joined table names into numerical
      features during inference.

    Training features include:
    - Log-transformed query row and column counts.
    - Row/column interaction features.
    - Join count.
    - Spatial query indicator.
    - Table join information encoded from table names.
    - Aggregate table shape information.

    The entire model state, including preprocessing components and the trained
    regressor, can be serialized with joblib for reuse in production.
    """

    def __init__(
        self,
        regressor: Pipeline,
        table_binarizer: MultiLabelBinarizer,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the query duration model."""
        self.regressor = regressor
        self.table_binarizer = table_binarizer
        self._metadata = metadata or {}

    @classmethod
    def train(
        cls,
        records: Iterable[QueryPerformance],
        alpha: float = 1.0,
    ) -> "QueryDurationModel":
        """Train a Ridge regression duration model."""
        records = list(records)

        x_array, y_array, table_encoder = _build_training_matrix(
            records,
        )

        model = make_pipeline(
            StandardScaler(),
            Ridge(alpha=alpha),
        )

        model.fit(
            x_array,
            y_array,
        )

        return cls(
            model,
            table_encoder,
            {
                "training_records": len(records),
            },
        )

    def predict(
        self,
        record: QueryPerformance,
    ) -> timedelta:
        """Predict query execution duration."""
        required_fields = {
            "joined_tables": record.joined_tables,
            "columns_fetched": record.columns_fetched,
            "rows_fetched": record.rows_fetched,
            "table_shapes": record.table_shapes,
        }

        missing_fields = [field for field, value in required_fields.items() if value is None]

        if missing_fields:
            msg = f"Cannot predict query duration. Missing required fields: {', '.join(missing_fields)}"
            raise ValueError(msg)

        numeric, tables, shapes = _duration_features(
            [record],
        )

        table_features = self.table_binarizer.transform(
            tables,
        )

        x_array = np.hstack(
            [
                numeric,
                shapes,
                table_features,
            ],
        )

        log_seconds = float(
            self.regressor.predict(x_array)[0],
        )

        seconds = max(
            np.expm1(log_seconds),
            0,
        )

        return timedelta(
            seconds=seconds,
        )

    def metadata(self) -> dict[str, Any]:
        """Return metadata describing this trained model."""
        ridge: Ridge = self.regressor[-1]

        return {
            "model_type": type(ridge).__name__,
            "parameters": {
                "alpha": ridge.alpha,
            },
            "sklearn_version": sklearn.__version__,
            "feature_count": len(ridge.coef_),
            "features": [
                "log_rows_fetched",
                "log_columns_fetched",
                "log_row_column_product",
                "join_count",
                "is_spatial",
                "log_table_rows",
                "log_table_columns",
                "log_table_cells",
                "joined_table_one_hot",
            ],
            **self._metadata,
        }

    def save(
        self,
        path: str | Path,
    ) -> None:
        """Save model to disk."""
        joblib.dump(
            self,
            path,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
    ) -> "QueryDurationModel":
        """Load model from disk."""
        return joblib.load(path)


def train_duration_model(
    records: Iterable[QueryPerformance],
    model_path: str | Path,
) -> QueryDurationModel:
    """Train and persist a query duration model."""
    model = QueryDurationModel.train(
        records,
    )

    model.save(
        model_path,
    )

    return model


def mae_seconds(
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> float:
    """Return mean absolute error in seconds by inverse-transforming log values.

    Both y_true and y_pred are expected to be log1p-transformed seconds.
    """
    return mean_absolute_error(
        np.expm1(y_true),
        np.expm1(y_pred),
    )


def evaluate_duration_model_kfold(
    records: Iterable[QueryPerformance],
    alpha: float = 1.0,
    n_splits: int = 5,
    random_state: int = 42,
) -> dict[str, float | list[float]]:
    """Evaluate Ridge model using K-fold cross validation."""
    x_array, y_array, _ = _build_training_matrix(
        records,
    )

    model = make_pipeline(
        StandardScaler(),
        Ridge(alpha=alpha),
    )

    kfold = KFold(
        n_splits=n_splits,
        shuffle=True,
        random_state=random_state,
    )

    predictions = cross_val_predict(
        model,
        x_array,
        y_array,
        cv=kfold,
    )

    return {
        "mae_seconds": float(
            mae_seconds(
                y_array,
                predictions,
            ),
        ),
        "record_count": len(y_array),
        "folds": n_splits,
    }


def tune_ridge_alpha(
    records: Iterable[QueryPerformance],
    alphas_to_test: list[float | int] | None = None,
) -> dict[str, float | int]:
    """Find the best Ridge alpha using cross validation.

    Pass `None` to use default set of Alpha values:
    0.001, 0.01, 0.1, 1, 10, 100, 1000.
    """
    x_array, y_array, _ = _build_training_matrix(
        records,
    )

    if not alphas_to_test:
        alphas_to_test = [
            0.001,
            0.01,
            0.1,
            1,
            10,
            100,
            1000,
        ]

    pipeline = Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "ridge",
                Ridge(),
            ),
        ],
    )

    scorer = make_scorer(
        mae_seconds,
        greater_is_better=False,
    )

    search = GridSearchCV(
        pipeline,
        {
            "ridge__alpha": alphas_to_test,
        },
        scoring=scorer,
        cv=5,
    )

    search.fit(
        x_array,
        y_array,
    )

    return {
        "best_alpha": search.best_params_["ridge__alpha"],
        "best_mae": float(-search.best_score_),
    }
