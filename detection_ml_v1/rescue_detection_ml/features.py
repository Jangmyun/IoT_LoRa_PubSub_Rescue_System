from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np
import pandas as pd


LABELS = ("CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH", "SENSOR_FAULT")
BASELINE_LABELS = ("CALM", "ENVIRONMENTAL_WAVE")
FAULT_LABEL = "SENSOR_FAULT"

FEATURE_COLUMNS = [
    "sonar_z",
    "accel_z",
    "sonar_rms_2s",
    "sonar_range_2s",
    "accel_rms_2s",
    "accel_jerk_2s",
]


@dataclass(frozen=True)
class DetectionFeatureConfig:
    """Feature defaults for TTGO LoRa32 + AJ-SR04M + MPU6050 experiments."""

    window_seconds: float = 2.0
    stride_seconds: float = 1.0
    baseline_minutes: float = 30.0
    min_samples_per_window: int = 3
    min_baseline_windows: int = 5
    g_ms2: float = 9.80665
    sonar_min_cm: float = 20.0
    sonar_max_cm: float = 450.0
    accel_min_ms2: float = 0.0
    accel_max_ms2: float = 80.0
    fault_rate_threshold: float = 0.25
    robust_epsilon: float = 1e-6

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def build_feature_table(
    raw: pd.DataFrame,
    config: DetectionFeatureConfig | None = None,
) -> pd.DataFrame:
    """Convert raw buoy samples into 2-second ML windows.

    Expected columns are ``timestamp_ms``, ``buoy_id``, ``sonar_cm`` and
    ``accel_mag_ms2``. A ``label`` column is required for training, but not for
    inference. Optional ``sonar_valid`` and ``sonar_timeout`` columns are used
    for rule-based fault handling when present.
    """

    config = config or DetectionFeatureConfig()
    _validate_required_columns(raw)

    frame = raw.copy()
    frame["timestamp_ms"] = pd.to_numeric(frame["timestamp_ms"], errors="coerce")
    frame["sonar_cm"] = pd.to_numeric(frame["sonar_cm"], errors="coerce")
    frame["accel_mag_ms2"] = pd.to_numeric(frame["accel_mag_ms2"], errors="coerce")
    frame["buoy_id"] = frame["buoy_id"].astype(str)
    if "label" in frame.columns:
        frame["label"] = frame["label"].astype(str).str.strip().str.upper()
        frame.loc[frame["label"].isin({"", "UNLABELED", "NONE", "NAN"}), "label"] = ""
        unknown = sorted(set(frame.loc[frame["label"].ne(""), "label"].dropna()) - set(LABELS))
        if unknown:
            raise ValueError(f"Unknown labels: {unknown}")

    frame["sample_fault"] = _sample_fault_mask(frame, config)

    windows: list[dict[str, object]] = []
    for buoy_id, buoy_frame in frame.sort_values(["buoy_id", "timestamp_ms"]).groupby("buoy_id"):
        windows.extend(_window_rows(str(buoy_id), buoy_frame, config))

    if not windows:
        return _empty_feature_table()

    features = pd.DataFrame(windows).sort_values(["buoy_id", "window_end_ms"]).reset_index(drop=True)
    features = _attach_rolling_baseline(features, config)
    for column in FEATURE_COLUMNS:
        features[column] = pd.to_numeric(features[column], errors="coerce").fillna(0.0)
    return features


def _validate_required_columns(frame: pd.DataFrame) -> None:
    required = {"timestamp_ms", "buoy_id", "sonar_cm", "accel_mag_ms2"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def _sample_fault_mask(frame: pd.DataFrame, config: DetectionFeatureConfig) -> pd.Series:
    sonar = frame["sonar_cm"]
    accel = frame["accel_mag_ms2"]
    finite_sonar = pd.Series(np.isfinite(sonar), index=frame.index)
    finite_accel = pd.Series(np.isfinite(accel), index=frame.index)
    fault = (
        frame["timestamp_ms"].isna()
        | sonar.isna()
        | accel.isna()
        | ~finite_sonar
        | ~finite_accel
        | (sonar < config.sonar_min_cm)
        | (sonar > config.sonar_max_cm)
        | (accel < config.accel_min_ms2)
        | (accel > config.accel_max_ms2)
    )

    if "sonar_valid" in frame.columns:
        fault |= ~frame["sonar_valid"].fillna(False).map(_truthy)
    if "sonar_timeout" in frame.columns:
        fault |= frame["sonar_timeout"].fillna(False).map(_truthy)
    if "label" in frame.columns:
        fault |= frame["label"].eq(FAULT_LABEL)
    return fault


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _window_rows(
    buoy_id: str,
    frame: pd.DataFrame,
    config: DetectionFeatureConfig,
) -> Iterable[dict[str, object]]:
    frame = frame.dropna(subset=["timestamp_ms"]).sort_values("timestamp_ms")
    if frame.empty:
        return []

    window_ms = int(config.window_seconds * 1000)
    stride_ms = int(config.stride_seconds * 1000)
    start = int(frame["timestamp_ms"].min())
    last = int(frame["timestamp_ms"].max())

    rows: list[dict[str, object]] = []
    while start <= last:
        end = start + window_ms
        window = frame[(frame["timestamp_ms"] >= start) & (frame["timestamp_ms"] < end)]
        if len(window) >= config.min_samples_per_window:
            rows.append(_summarize_window(buoy_id, start, end, window, config))
        start += stride_ms
    return rows


def _summarize_window(
    buoy_id: str,
    start_ms: int,
    end_ms: int,
    window: pd.DataFrame,
    config: DetectionFeatureConfig,
) -> dict[str, object]:
    valid = window[~window["sample_fault"]]
    sonar = valid["sonar_cm"].to_numpy(dtype=float)
    accel = valid["accel_mag_ms2"].to_numpy(dtype=float)
    time_s = valid["timestamp_ms"].to_numpy(dtype=float) / 1000.0

    fault_rate = float(window["sample_fault"].mean())
    rule_label = FAULT_LABEL if fault_rate >= config.fault_rate_threshold else ""
    label = _window_label(window, rule_label)

    sonar_rms = _rms(sonar - np.median(sonar)) if sonar.size else 0.0
    accel_dynamic = accel - np.median(accel) if accel.size else np.asarray([], dtype=float)

    return {
        "buoy_id": buoy_id,
        "window_start_ms": start_ms,
        "window_end_ms": end_ms,
        "sample_count": int(len(window)),
        "valid_sample_count": int(len(valid)),
        "fault_rate": fault_rate,
        "rule_label": rule_label,
        "label": label,
        "sonar_mean_cm": _safe_stat(np.mean, sonar),
        "sonar_median_cm": _safe_stat(np.median, sonar),
        "sonar_rms_2s": sonar_rms,
        "sonar_range_2s": _safe_range(sonar),
        "sonar_velocity_rms": _velocity_rms(sonar, time_s),
        "accel_mean_ms2": _safe_stat(np.mean, accel),
        "accel_rms_2s": _rms(accel_dynamic),
        "accel_range_2s": _safe_range(accel),
        "accel_jerk_2s": _velocity_rms(accel, time_s),
    }


def _window_label(window: pd.DataFrame, rule_label: str) -> str:
    if rule_label:
        return rule_label
    if "label" not in window.columns:
        return ""
    labels = window.loc[~window["label"].eq(FAULT_LABEL), "label"]
    if labels.empty:
        return FAULT_LABEL
    return str(labels.mode(dropna=True).iloc[0])


def _safe_stat(fn, values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(fn(values))


def _safe_range(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(np.max(values) - np.min(values))


def _rms(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(values))))


def _velocity_rms(values: np.ndarray, time_s: np.ndarray) -> float:
    if values.size < 2:
        return 0.0
    dt = np.diff(time_s)
    diff = np.diff(values)
    valid = dt > 0
    if not np.any(valid):
        return 0.0
    return _rms(diff[valid] / dt[valid])


def _attach_rolling_baseline(
    features: pd.DataFrame,
    config: DetectionFeatureConfig,
) -> pd.DataFrame:
    out = features.copy()
    out["sonar_z"] = 0.0
    out["accel_z"] = 0.0
    out["baseline_window_count"] = 0

    baseline_ms = config.baseline_minutes * 60.0 * 1000.0
    for buoy_id, indices in out.groupby("buoy_id").groups.items():
        group = out.loc[indices].sort_values("window_end_ms")
        for index, row in group.iterrows():
            history = group[group["window_end_ms"] < row["window_end_ms"]]
            history = history[history["window_end_ms"] >= row["window_end_ms"] - baseline_ms]
            history = history[_is_baseline_row(history)]
            out.at[index, "baseline_window_count"] = int(len(history))

            out.at[index, "sonar_z"] = _robust_z_from_history(
                float(row["sonar_rms_2s"]),
                history["sonar_rms_2s"],
                config,
            )
            out.at[index, "accel_z"] = _robust_z_from_history(
                float(row["accel_rms_2s"]),
                history["accel_rms_2s"],
                config,
            )
    return out


def _is_baseline_row(frame: pd.DataFrame) -> pd.Series:
    if "label" in frame.columns and frame["label"].ne("").any():
        return frame["label"].isin(BASELINE_LABELS) & frame["rule_label"].eq("")
    return frame["rule_label"].eq("")


def _robust_z_from_history(
    value: float,
    history: pd.Series,
    config: DetectionFeatureConfig,
) -> float:
    history = pd.to_numeric(history, errors="coerce").dropna()
    if len(history) < config.min_baseline_windows:
        return 0.0
    center = float(np.median(history))
    mad = float(np.median(np.abs(history.to_numpy(dtype=float) - center)))
    scale = max(1.4826 * mad, float(np.std(history)), config.robust_epsilon)
    return max(0.0, abs(value - center) / scale - 1.0)


def _empty_feature_table() -> pd.DataFrame:
    columns = [
        "buoy_id",
        "window_start_ms",
        "window_end_ms",
        "sample_count",
        "valid_sample_count",
        "fault_rate",
        "rule_label",
        "label",
        "sonar_mean_cm",
        "sonar_median_cm",
        "sonar_rms_2s",
        "sonar_range_2s",
        "sonar_velocity_rms",
        "accel_mean_ms2",
        "accel_rms_2s",
        "accel_range_2s",
        "accel_jerk_2s",
        "sonar_z",
        "accel_z",
        "baseline_window_count",
    ]
    return pd.DataFrame(columns=columns)
