from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, train_test_split
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
    cv_folds: int = 5,
    test_size: float = 0.25,
) -> TrainingResult:
    """Train and compare the v1 scikit-learn model candidates."""

    feature_columns = feature_columns or FEATURE_COLUMNS
    training = _training_rows(feature_table)
    _validate_training_frame(training, feature_columns)

    x = training[feature_columns].astype(float)
    y = training["label"].astype(str)
    metrics, reports = _evaluate_candidate_models(x, y, cv_folds, test_size)

    metrics_frame = pd.DataFrame(metrics).sort_values(
        ["macro_f1", "accuracy"],
        ascending=False,
    )
    best_name = str(metrics_frame.iloc[0]["model"])
    best_model = MODEL_FACTORIES[best_name]()
    best_model.fit(x, y)
    report_truth, report_predictions = reports[best_name]

    bundle = {
        "model": best_model,
        "best_model_name": best_name,
        "feature_columns": feature_columns,
        "feature_config": feature_config or {},
        "cv_folds": int(metrics_frame.iloc[0]["cv_folds"]),
        "labels": [label for label in LABELS if label != FAULT_LABEL],
        "rule_based_fault_label": FAULT_LABEL,
        "classification_report": classification_report(
            report_truth,
            report_predictions,
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


def _evaluate_candidate_models(
    x: pd.DataFrame,
    y: pd.Series,
    requested_folds: int,
    test_size: float,
) -> tuple[list[dict[str, object]], dict[str, tuple[list[str], list[str]]]]:
    folds = _effective_cv_folds(y, requested_folds)
    if folds >= 2:
        return _evaluate_with_stratified_kfold(x, y, folds)
    return _evaluate_with_holdout(x, y, test_size)


def _effective_cv_folds(y: pd.Series, requested_folds: int) -> int:
    if requested_folds < 2:
        return 1
    class_counts = y.value_counts()
    if len(class_counts) < 2:
        return 1
    return min(int(requested_folds), int(class_counts.min()))


def _evaluate_with_stratified_kfold(
    x: pd.DataFrame,
    y: pd.Series,
    folds: int,
) -> tuple[list[dict[str, object]], dict[str, tuple[list[str], list[str]]]]:
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    metrics: list[dict[str, object]] = []
    reports: dict[str, tuple[list[str], list[str]]] = {}

    for name, factory in MODEL_FACTORIES.items():
        truth: list[str] = []
        predictions: list[str] = []
        fold_macro_f1: list[float] = []
        for train_index, test_index in splitter.split(x, y):
            model = factory()
            x_train, x_test = x.iloc[train_index], x.iloc[test_index]
            y_train, y_test = y.iloc[train_index], y.iloc[test_index]
            model.fit(x_train, y_train)
            fold_predictions = [str(item) for item in model.predict(x_test)]
            fold_truth = [str(item) for item in y_test.tolist()]
            truth.extend(fold_truth)
            predictions.extend(fold_predictions)
            fold_macro_f1.append(f1_score(fold_truth, fold_predictions, average="macro"))

        metrics.append(_metric_row(name, truth, predictions, folds, fold_macro_f1))
        reports[name] = (truth, predictions)

    return metrics, reports


def _evaluate_with_holdout(
    x: pd.DataFrame,
    y: pd.Series,
    test_size: float,
) -> tuple[list[dict[str, object]], dict[str, tuple[list[str], list[str]]]]:
    x_train, x_test, y_train, y_test = _split_training_data(x, y, test_size)
    metrics: list[dict[str, object]] = []
    reports: dict[str, tuple[list[str], list[str]]] = {}

    for name, factory in MODEL_FACTORIES.items():
        model = factory()
        model.fit(x_train, y_train)
        truth = [str(item) for item in y_test.tolist()]
        predictions = [str(item) for item in model.predict(x_test)]
        metrics.append(_metric_row(name, truth, predictions, 1, []))
        reports[name] = (truth, predictions)

    return metrics, reports


def _metric_row(
    model_name: str,
    truth: list[str],
    predictions: list[str],
    cv_folds: int,
    fold_macro_f1: list[float],
) -> dict[str, object]:
    macro_f1_std = pd.Series(fold_macro_f1).std(ddof=0) if fold_macro_f1 else 0.0
    return {
        "model": model_name,
        "accuracy": accuracy_score(truth, predictions),
        "macro_f1": f1_score(truth, predictions, average="macro"),
        "weighted_f1": f1_score(truth, predictions, average="weighted"),
        "macro_f1_std": float(macro_f1_std),
        "cv_folds": cv_folds,
        "test_windows": len(truth),
    }
