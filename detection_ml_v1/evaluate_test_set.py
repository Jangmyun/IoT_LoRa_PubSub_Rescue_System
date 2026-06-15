#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from prepare_labeled_dataset import load_collection_csv, parse_run_spec, trim_by_elapsed_seconds
from rescue_detection_ml.config import infer_median_sample_seconds
from rescue_detection_ml.features import DetectionFeatureConfig, build_feature_table
from rescue_detection_ml.modeling import load_model_bundle, predict_feature_table


DEFAULT_TEST_LABELS = {
    "csv_result_001.csv": "CALM",
    "csv_result_002.csv": "ENVIRONMENTAL_WAVE",
    "csv_result_003.csv": "ENVIRONMENTAL_WAVE",
    "csv_result_004.csv": "DUMMY_SPLASH",
}
REPORT_LABELS = ["CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH"]
VICTIM_LABEL = "DUMMY_SPLASH"


def load_pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "matplotlib is required to generate graphs. "
            "Install detection_ml_v1/requirements.txt first."
        ) from exc
    return plt


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Evaluate the trained accel-only rescue detector on labeled test CSV files."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=base_dir / "models" / "bath_accel_only_v2" / "model.joblib",
        help="Path to model.joblib.",
    )
    parser.add_argument(
        "--test-dir",
        type=Path,
        default=base_dir / "test",
        help="Directory containing csv_result_001.csv ... csv_result_004.csv.",
    )
    parser.add_argument(
        "--run",
        action="append",
        help="Optional explicit mapping PATH=LABEL. Overrides the default test-dir mapping.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=base_dir / "artifacts" / "test_set_eval_v1",
        help="Directory for metrics, predictions, and PNG graphs.",
    )
    parser.add_argument("--trim-start-seconds", type=float, default=0.0)
    parser.add_argument("--trim-end-seconds", type=float, default=0.0)
    parser.add_argument(
        "--suspect-threshold",
        type=float,
        default=0.30,
        help="Victim probability threshold used by the web server to raise SUSPECT.",
    )
    parser.add_argument("--window-seconds", type=float, default=None)
    parser.add_argument("--stride-seconds", type=float, default=None)
    parser.add_argument("--baseline-minutes", type=float, default=None)
    return parser.parse_args()


def default_run_specs(test_dir: Path) -> list[str]:
    return [
        f"{test_dir / filename}={label}"
        for filename, label in DEFAULT_TEST_LABELS.items()
    ]


def load_labeled_runs(
    specs: list[str],
    trim_start_seconds: float,
    trim_end_seconds: float,
) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for spec in specs:
        path, label, buoy_id = parse_run_spec(spec)
        if buoy_id is not None:
            raise ValueError("Test evaluation does not support @BUOY_ID filters")
        frame = load_collection_csv(path, label)
        frame = trim_by_elapsed_seconds(frame, trim_start_seconds, trim_end_seconds)
        frame["source_file"] = path.name
        frames.append(frame.reset_index(drop=True))
    return frames


def resolve_eval_config(
    raw: pd.DataFrame,
    bundle: dict[str, Any],
    *,
    window_seconds: float | None,
    stride_seconds: float | None,
    baseline_minutes: float | None,
) -> tuple[DetectionFeatureConfig, float | None]:
    base = DetectionFeatureConfig(**bundle.get("feature_config", {}))
    sample_seconds = infer_median_sample_seconds(raw)
    return (
        replace(
            base,
            window_seconds=window_seconds if window_seconds is not None else base.window_seconds,
            stride_seconds=stride_seconds if stride_seconds is not None else base.stride_seconds,
            baseline_minutes=baseline_minutes if baseline_minutes is not None else base.baseline_minutes,
        ),
        sample_seconds,
    )


def build_predictions_by_source(
    frames: list[pd.DataFrame],
    bundle: dict[str, Any],
    config: DetectionFeatureConfig,
    suspect_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_frames: list[pd.DataFrame] = []
    prediction_frames: list[pd.DataFrame] = []

    for raw in frames:
        source_file = str(raw["source_file"].iloc[0])
        features = build_feature_table(raw, config)
        if features.empty:
            continue
        features["source_file"] = source_file
        predictions = predict_feature_table(bundle, features)
        predictions = add_probability_columns(bundle, predictions, suspect_threshold)
        predictions["source_file"] = source_file
        feature_frames.append(features)
        prediction_frames.append(predictions)

    if not prediction_frames:
        raise ValueError("No feature windows were produced from the test CSV files")

    return (
        pd.concat(feature_frames, ignore_index=True),
        pd.concat(prediction_frames, ignore_index=True),
    )


def add_probability_columns(
    bundle: dict[str, Any],
    predictions: pd.DataFrame,
    suspect_threshold: float,
) -> pd.DataFrame:
    out = predictions.copy()
    model = bundle["model"]
    feature_columns = list(bundle["feature_columns"])
    classes = model_classes(model)

    out["victim_probability"] = 0.0
    for label in REPORT_LABELS:
        out[f"prob_{label}"] = 0.0

    if hasattr(model, "predict_proba") and classes:
        probabilities = model.predict_proba(out[feature_columns].astype(float))
        for index, label in enumerate(classes):
            column = f"prob_{label}"
            out[column] = probabilities[:, index]
        if f"prob_{VICTIM_LABEL}" in out.columns:
            out["victim_probability"] = out[f"prob_{VICTIM_LABEL}"]

    out["actual_victim"] = out["label"].eq(VICTIM_LABEL)
    out["predicted_alert"] = (
        out["predicted_label"].eq(VICTIM_LABEL)
        | out["victim_probability"].ge(suspect_threshold)
    )
    out["prediction_correct"] = out["label"].eq(out["predicted_label"])
    return out


def model_classes(model: Any) -> list[str]:
    classes = getattr(model, "classes_", None)
    if classes is None and hasattr(model, "steps") and model.steps:
        classes = getattr(model.steps[-1][1], "classes_", None)
    return [str(label) for label in classes] if classes is not None else []


def compute_multiclass_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    y_true = predictions["label"].astype(str)
    y_pred = predictions["predicted_label"].astype(str)
    report = classification_report(
        y_true,
        y_pred,
        labels=REPORT_LABELS,
        zero_division=0,
        output_dict=True,
    )
    rows = []
    for label in REPORT_LABELS:
        rows.append(
            {
                "label": label,
                "precision": report[label]["precision"],
                "recall": report[label]["recall"],
                "f1": report[label]["f1-score"],
                "support": int(report[label]["support"]),
            }
        )
    rows.append(
        {
            "label": "overall",
            "precision": precision_score(y_true, y_pred, average="weighted", zero_division=0),
            "recall": recall_score(y_true, y_pred, average="weighted", zero_division=0),
            "f1": f1_score(y_true, y_pred, average="weighted", zero_division=0),
            "support": len(predictions),
        }
    )
    return pd.DataFrame(rows)


def compute_binary_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    actual = predictions["actual_victim"].astype(bool)
    predicted = predictions["predicted_alert"].astype(bool)
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[False, True]).ravel()
    total = tp + fp + fn + tn
    return pd.DataFrame(
        [
            {
                "tp": int(tp),
                "fp": int(fp),
                "fn": int(fn),
                "tn": int(tn),
                "accuracy": (tp + tn) / total if total else 0.0,
                "precision": tp / (tp + fp) if tp + fp else 0.0,
                "recall": tp / (tp + fn) if tp + fn else 0.0,
                "false_negative_rate": fn / (tp + fn) if tp + fn else 0.0,
                "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
            }
        ]
    )


def compute_source_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source_file, frame in predictions.groupby("source_file"):
        binary = compute_binary_metrics(frame).iloc[0].to_dict()
        rows.append(
            {
                "source_file": source_file,
                "label": str(frame["label"].mode().iloc[0]),
                "windows": len(frame),
                "multiclass_accuracy": accuracy_score(frame["label"], frame["predicted_label"]),
                **binary,
            }
        )
    return pd.DataFrame(rows).sort_values("source_file")


def save_graphs(
    predictions: pd.DataFrame,
    multiclass_metrics: pd.DataFrame,
    output_dir: Path,
    suspect_threshold: float,
) -> list[Path]:
    paths = [
        plot_confusion_matrix(
            predictions["label"],
            predictions["predicted_label"],
            REPORT_LABELS,
            "Multiclass Prediction Confusion Matrix",
            output_dir / "01_multiclass_confusion_matrix.png",
        ),
        plot_confusion_matrix(
            predictions["actual_victim"],
            predictions["predicted_alert"],
            [False, True],
            "Binary Alert Confusion Matrix",
            output_dir / "02_binary_alert_confusion_matrix.png",
            tick_labels=["No Victim", "Victim / Alert"],
        ),
        plot_per_class_metrics(
            multiclass_metrics,
            output_dir / "03_per_class_precision_recall_f1.png",
        ),
        plot_victim_probability_by_source(
            predictions,
            suspect_threshold,
            output_dir / "04_victim_probability_by_source.png",
        ),
        plot_prediction_counts_by_source(
            predictions,
            output_dir / "05_prediction_counts_by_source.png",
        ),
    ]
    return paths


def plot_confusion_matrix(
    y_true: pd.Series,
    y_pred: pd.Series,
    labels: list[Any],
    title: str,
    output_path: Path,
    tick_labels: list[str] | None = None,
) -> Path:
    plt = load_pyplot()
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    display_labels = tick_labels or [str(label) for label in labels]
    fig, ax = plt.subplots(figsize=(7.2, 5.8))
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_title(title)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_xticks(range(len(labels)), display_labels, rotation=25, ha="right")
    ax.set_yticks(range(len(labels)), display_labels)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, str(matrix[i, j]), ha="center", va="center", color="black")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def plot_per_class_metrics(metrics: pd.DataFrame, output_path: Path) -> Path:
    plt = load_pyplot()
    frame = metrics[metrics["label"].isin(REPORT_LABELS)].copy()
    x = np.arange(len(frame))
    width = 0.24
    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    for offset, column in [(-width, "precision"), (0, "recall"), (width, "f1")]:
        ax.bar(x + offset, frame[column], width, label=column)
    ax.set_title("Per-Class Precision / Recall / F1")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x, frame["label"], rotation=20, ha="right")
    ax.set_ylabel("Score")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def plot_victim_probability_by_source(
    predictions: pd.DataFrame,
    suspect_threshold: float,
    output_path: Path,
) -> Path:
    plt = load_pyplot()
    sources = sorted(predictions["source_file"].unique())
    values = [
        predictions.loc[predictions["source_file"].eq(source), "victim_probability"].to_numpy()
        for source in sources
    ]
    fig, ax = plt.subplots(figsize=(9.2, 5.2))
    ax.boxplot(values, tick_labels=sources, showmeans=True)
    for index, source in enumerate(sources, start=1):
        y = predictions.loc[predictions["source_file"].eq(source), "victim_probability"].to_numpy()
        x = np.full(len(y), index, dtype=float)
        ax.scatter(x, y, s=24, alpha=0.65)
    ax.axhline(suspect_threshold, color="red", linestyle="--", label=f"SUSPECT threshold={suspect_threshold:.2f}")
    ax.set_title("Victim Probability by Test CSV")
    ax.set_ylabel("DUMMY_SPLASH probability")
    ax.set_ylim(-0.03, 1.03)
    ax.tick_params(axis="x", rotation=20)
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def plot_prediction_counts_by_source(predictions: pd.DataFrame, output_path: Path) -> Path:
    plt = load_pyplot()
    counts = (
        predictions.groupby(["source_file", "predicted_label"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=REPORT_LABELS, fill_value=0)
        .sort_index()
    )
    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    bottom = np.zeros(len(counts))
    x = np.arange(len(counts))
    for label in REPORT_LABELS:
        values = counts[label].to_numpy()
        ax.bar(x, values, bottom=bottom, label=label)
        bottom += values
    ax.set_title("Predicted Label Counts by Test CSV")
    ax.set_ylabel("Feature windows")
    ax.set_xticks(x, counts.index, rotation=20, ha="right")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def write_summary(
    output_path: Path,
    predictions: pd.DataFrame,
    binary_metrics: pd.DataFrame,
    multiclass_metrics: pd.DataFrame,
    source_metrics: pd.DataFrame,
    graph_paths: list[Path],
    *,
    model_path: Path,
    sample_seconds: float | None,
    config: DetectionFeatureConfig,
    suspect_threshold: float,
) -> None:
    binary = binary_metrics.iloc[0]
    overall = multiclass_metrics[multiclass_metrics["label"].eq("overall")].iloc[0]
    sample_text = "unknown" if sample_seconds is None else f"{sample_seconds:.3f}s"
    lines = [
        "# Test Set Evaluation",
        "",
        f"- Model: `{model_path}`",
        f"- Windows: {len(predictions)}",
        f"- Window/stride: {config.window_seconds:g}s / {config.stride_seconds:g}s",
        f"- Median sample interval: {sample_text}",
        f"- SUSPECT threshold: {suspect_threshold:.2f}",
        "",
        "## Binary Alert Metrics",
        "",
        f"- Accuracy: {binary['accuracy']:.4f}",
        f"- Precision: {binary['precision']:.4f}",
        f"- Recall: {binary['recall']:.4f}",
        f"- False negative rate: {binary['false_negative_rate']:.4f}",
        f"- False positive rate: {binary['false_positive_rate']:.4f}",
        f"- TP/FP/FN/TN: {int(binary['tp'])}/{int(binary['fp'])}/{int(binary['fn'])}/{int(binary['tn'])}",
        "",
        "## Multiclass Metrics",
        "",
        f"- Weighted F1: {overall['f1']:.4f}",
        f"- Weighted precision: {overall['precision']:.4f}",
        f"- Weighted recall: {overall['recall']:.4f}",
        "",
        "## Per Source",
        "",
        "```text",
        source_metrics.to_string(index=False),
        "```",
        "",
        "## Graphs",
        "",
        *[f"- `{path.name}`" for path in graph_paths],
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    specs = args.run or default_run_specs(args.test_dir)
    bundle = load_model_bundle(args.model)
    frames = load_labeled_runs(specs, args.trim_start_seconds, args.trim_end_seconds)
    raw = pd.concat(frames, ignore_index=True)
    config, sample_seconds = resolve_eval_config(
        raw,
        bundle,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        baseline_minutes=args.baseline_minutes,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(args.output_dir / "test_labeled_raw.csv", index=False)
    features, predictions = build_predictions_by_source(
        frames,
        bundle,
        config,
        args.suspect_threshold,
    )
    features.to_csv(args.output_dir / "test_feature_windows.csv", index=False)
    predictions.to_csv(args.output_dir / "test_predictions.csv", index=False)

    multiclass_metrics = compute_multiclass_metrics(predictions)
    binary_metrics = compute_binary_metrics(predictions)
    source_metrics = compute_source_metrics(predictions)
    multiclass_metrics.to_csv(args.output_dir / "multiclass_metrics.csv", index=False)
    binary_metrics.to_csv(args.output_dir / "binary_alert_metrics.csv", index=False)
    source_metrics.to_csv(args.output_dir / "source_metrics.csv", index=False)

    graph_paths = save_graphs(
        predictions,
        multiclass_metrics,
        args.output_dir,
        args.suspect_threshold,
    )
    write_summary(
        args.output_dir / "summary.md",
        predictions,
        binary_metrics,
        multiclass_metrics,
        source_metrics,
        graph_paths,
        model_path=args.model,
        sample_seconds=sample_seconds,
        config=config,
        suspect_threshold=args.suspect_threshold,
    )

    binary = binary_metrics.iloc[0]
    overall_accuracy = accuracy_score(predictions["label"], predictions["predicted_label"])
    print(f"output_dir={args.output_dir}")
    print(f"windows={len(predictions)}")
    print(f"multiclass_accuracy={overall_accuracy:.4f}")
    print(f"binary_alert_accuracy={binary['accuracy']:.4f}")
    print(f"false_negative_rate={binary['false_negative_rate']:.4f}")
    print(f"false_positive_rate={binary['false_positive_rate']:.4f}")
    print(f"tp_fp_fn_tn={int(binary['tp'])}/{int(binary['fp'])}/{int(binary['fn'])}/{int(binary['tn'])}")


if __name__ == "__main__":
    main()
