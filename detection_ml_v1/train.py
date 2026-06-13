#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from rescue_detection_ml.config import resolve_feature_config
from rescue_detection_ml.features import build_feature_table
from rescue_detection_ml.modeling import train_candidate_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train v1 buoy disturbance classifiers from labeled sensor CSV."
    )
    parser.add_argument("--csv", required=True, type=Path, help="Labeled raw measurement CSV.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("detection_ml_v1/artifacts"),
        help="Directory for model.joblib, metrics.csv, and feature_windows.csv.",
    )
    parser.add_argument("--baseline-minutes", type=float, default=30.0)
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=None,
        help="Defaults to 2s for fast serial CSV, 10s for sparse LoRa CSV.",
    )
    parser.add_argument(
        "--stride-seconds",
        type=float,
        default=None,
        help="Defaults to 1s for fast serial CSV, 5s for sparse LoRa CSV.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw = pd.read_csv(args.csv)
    config, sample_seconds, auto_selected = resolve_feature_config(
        raw,
        baseline_minutes=args.baseline_minutes,
        window_seconds=args.window_seconds,
        stride_seconds=args.stride_seconds,
    )
    features = build_feature_table(raw, config)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output_dir / "feature_windows.csv", index=False)

    result = train_candidate_models(features, args.output_dir, feature_config=config.to_dict())
    if auto_selected:
        sample_text = "unknown" if sample_seconds is None else f"{sample_seconds:.3f}s"
        print(
            "auto_window="
            f"{config.window_seconds:.1f}s stride={config.stride_seconds:.1f}s "
            f"median_sample_interval={sample_text}"
        )
    print(f"trained_windows={len(features)}")
    print(f"best_model={result.best_model_name}")
    print(result.metrics.to_string(index=False))
    print(f"saved_model={args.output_dir / 'model.joblib'}")


if __name__ == "__main__":
    main()
