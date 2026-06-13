from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from .features import DetectionFeatureConfig


FAST_SAMPLE_THRESHOLD_SECONDS = 1.0
FAST_WINDOW_SECONDS = 2.0
FAST_STRIDE_SECONDS = 1.0
LORA_WINDOW_SECONDS = 10.0
LORA_STRIDE_SECONDS = 5.0


def infer_median_sample_seconds(raw: pd.DataFrame) -> float | None:
    """Estimate the median sample interval per buoy from timestamp_ms."""

    if "timestamp_ms" not in raw.columns:
        return None
    frame = raw.copy()
    frame["timestamp_ms"] = pd.to_numeric(frame["timestamp_ms"], errors="coerce")
    if "buoy_id" not in frame.columns:
        frame["buoy_id"] = "default"

    diffs: list[float] = []
    for _, group in frame.dropna(subset=["timestamp_ms"]).groupby("buoy_id"):
        values = np.sort(group["timestamp_ms"].to_numpy(dtype=float))
        positive = np.diff(values)
        positive = positive[positive > 0]
        diffs.extend((positive / 1000.0).tolist())

    if not diffs:
        return None
    return float(np.median(diffs))


def choose_window_defaults(raw: pd.DataFrame) -> tuple[float, float, float | None]:
    """Return window/stride defaults based on sample density."""

    sample_seconds = infer_median_sample_seconds(raw)
    if sample_seconds is not None and sample_seconds > FAST_SAMPLE_THRESHOLD_SECONDS:
        return LORA_WINDOW_SECONDS, LORA_STRIDE_SECONDS, sample_seconds
    return FAST_WINDOW_SECONDS, FAST_STRIDE_SECONDS, sample_seconds


def resolve_feature_config(
    raw: pd.DataFrame,
    baseline_minutes: float | None = None,
    window_seconds: float | None = None,
    stride_seconds: float | None = None,
    fallback: DetectionFeatureConfig | None = None,
) -> tuple[DetectionFeatureConfig, float | None, bool]:
    """Build a feature config, auto-selecting window/stride when omitted."""

    base = fallback or DetectionFeatureConfig()
    default_window, default_stride, sample_seconds = choose_window_defaults(raw)
    auto_selected = window_seconds is None and stride_seconds is None

    config = replace(
        base,
        baseline_minutes=baseline_minutes if baseline_minutes is not None else base.baseline_minutes,
        window_seconds=window_seconds if window_seconds is not None else default_window,
        stride_seconds=stride_seconds if stride_seconds is not None else default_stride,
    )
    return config, sample_seconds, auto_selected
