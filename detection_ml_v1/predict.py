#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from rescue_detection_ml.config import resolve_feature_config
from rescue_detection_ml.features import DetectionFeatureConfig, build_feature_table
from rescue_detection_ml.modeling import load_model_bundle, predict_feature_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Predict v1 buoy disturbance labels from raw sensor CSV."
    )
    parser.add_argument("--csv", required=True, type=Path, help="Raw measurement CSV.")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("detection_ml_v1/artifacts/model.joblib"),
        help="Path to model.joblib produced by train.py.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("detection_ml_v1/artifacts/predictions.csv"),
        help="Prediction CSV output path.",
    )
    parser.add_argument("--baseline-minutes", type=float, default=None)
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=None,
        help="Defaults to the model's training window when available.",
    )
    parser.add_argument(
        "--stride-seconds",
        type=float,
        default=None,
        help="Defaults to the model's training stride when available.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = pd.read_csv(args.csv)
    bundle = load_model_bundle(args.model)
    fallback = DetectionFeatureConfig(**bundle.get("feature_config", {}))
    config, sample_seconds, auto_selected = resolve_feature_config(
        raw,
        baseline_minutes=args.baseline_minutes,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
        fallback=fallback,
    )
    features = build_feature_table(raw, config)
    predictions = predict_feature_table(bundle, features)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(args.output, index=False)
    if auto_selected:
        sample_text = "unknown" if sample_seconds is None else f"{sample_seconds:.3f}s"
        print(
            "auto_window="
            f"{config.window_seconds:.1f}s stride={config.stride_seconds:.1f}s "
            f"median_sample_interval={sample_text}"
        )
    print(f"predicted_windows={len(predictions)}")
    print(f"saved_predictions={args.output}")


if __name__ == "__main__":
    main()
