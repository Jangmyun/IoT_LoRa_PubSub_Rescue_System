from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from .features import FAULT_LABEL, FEATURE_COLUMNS, LABELS


MODEL_FACTORIES = {
    "decision_tree": lambda: DecisionTreeClassifier(
        max_depth=6,
        class_weight="balanced",
        random_state=42,
    ),
    "random_forest": lambda: RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    ),
    "hist_gradient_boosting": lambda: make_pipeline(
        StandardScaler(),
        HistGradientBoostingClassifier(
            max_iter=200,
            learning_rate=0.08,
            random_state=42,
        ),
    ),
}


@dataclass(frozen=True)
class TrainingResult:
    best_model_name: str
    metrics: pd.DataFrame
    bundle: dict[str, Any]


def train_candidate_models(
    feature_table: pd.DataFrame,
    output_dir: str | Path,
    feature_columns: list[str] | None = None,
    feature_config: dict[str, Any] | None = None,
    test_size: float = 0.25,
) -> TrainingResult:
    """Train and compare the v1 scikit-learn model candidates."""

    feature_columns = feature_columns or FEATURE_COLUMNS
    training = _training_rows(feature_table)
    _validate_training_frame(training, feature_columns)

    x = training[feature_columns].astype(float)
    y = training["label"].astype(str)
    x_train, x_test, y_train, y_test = _split_training_data(x, y, test_size)

    metrics: list[dict[str, object]] = []
    fitted: dict[str, Any] = {}
    for name, factory in MODEL_FACTORIES.items():
        model = factory()
        model.fit(x_train, y_train)
        predictions = model.predict(x_test)
        metrics.append(
            {
                "model": name,
                "accuracy": accuracy_score(y_test, predictions),
                "macro_f1": f1_score(y_test, predictions, average="macro"),
                "weighted_f1": f1_score(y_test, predictions, average="weighted"),
                "test_windows": len(y_test),
            }
        )
        fitted[name] = model

    metrics_frame = pd.DataFrame(metrics).sort_values(
        ["macro_f1", "accuracy"],
        ascending=False,
    )
    best_name = str(metrics_frame.iloc[0]["model"])
    best_model = fitted[best_name]

    bundle = {
        "model": best_model,
        "best_model_name": best_name,
        "feature_columns": feature_columns,
        "feature_config": feature_config or {},
        "labels": [label for label in LABELS if label != FAULT_LABEL],
        "rule_based_fault_label": FAULT_LABEL,
        "classification_report": classification_report(
            y_test,
            best_model.predict(x_test),
            zero_division=0,
            output_dict=True,
        ),
    }

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output_path / "model.joblib")
    metrics_frame.to_csv(output_path / "metrics.csv", index=False)
    return TrainingResult(best_name, metrics_frame, bundle)


def predict_feature_table(
    bundle: dict[str, Any],
    feature_table: pd.DataFrame,
) -> pd.DataFrame:
    """Predict labels and keep rule-based SENSOR_FAULT ahead of ML output."""

    feature_columns = list(bundle["feature_columns"])
    missing = sorted(set(feature_columns) - set(feature_table.columns))
    if missing:
        raise ValueError(f"Feature table is missing columns: {missing}")

    out = feature_table.copy()
    out["predicted_label"] = ""
    fault_mask = out["rule_label"].eq(FAULT_LABEL)
    non_fault = ~fault_mask

    out.loc[fault_mask, "predicted_label"] = FAULT_LABEL
    if non_fault.any():
        model = bundle["model"]
        predictions = model.predict(out.loc[non_fault, feature_columns].astype(float))
        out.loc[non_fault, "predicted_label"] = predictions
    return out


def load_model_bundle(path: str | Path) -> dict[str, Any]:
    return joblib.load(path)


def _training_rows(feature_table: pd.DataFrame) -> pd.DataFrame:
    if "label" not in feature_table.columns:
        raise ValueError("Training requires a label column")
    return feature_table[
        feature_table["label"].ne("")
        & feature_table["label"].ne(FAULT_LABEL)
        & feature_table["rule_label"].ne(FAULT_LABEL)
    ].copy()


def _validate_training_frame(frame: pd.DataFrame, feature_columns: list[str]) -> None:
    missing = sorted(set(feature_columns + ["label"]) - set(frame.columns))
    if missing:
        raise ValueError(f"Training data is missing columns: {missing}")
    if frame.empty:
        raise ValueError("No non-fault windows are available for ML training")
    if frame["label"].nunique() < 2:
        raise ValueError("Training requires at least two non-fault labels")


def _split_training_data(
    x: pd.DataFrame,
    y: pd.Series,
    test_size: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    class_counts = y.value_counts()
    can_stratify = len(class_counts) >= 2 and class_counts.min() >= 2
    if len(y) < 8 or not can_stratify:
        return x, x, y, y
    return train_test_split(
        x,
        y,
        test_size=test_size,
        random_state=42,
        stratify=y,
    )
