#!/usr/bin/env python3
"""Generate explanatory SVG graphs for the shallow-lake detection design.

Without --csv, deterministic synthetic data is used. With --csv, time-series
figures use the supplied measurements while conceptual figures remain synthetic.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np


SEED = 20260612
REQUIRED_COLUMNS = {
    "timestamp_ms",
    "buoy_id",
    "sonar_cm",
    "accel_mag_ms2",
    "gyro_mag_rads",
    "label",
}
LABELS = ("CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH", "SENSOR_FAULT")
COLORS = {
    "CALM": "#2a9d8f",
    "ENVIRONMENTAL_WAVE": "#457b9d",
    "DUMMY_SPLASH": "#e76f51",
    "SENSOR_FAULT": "#7b2cbf",
}


@dataclass
class Measurements:
    time_s: np.ndarray
    buoy_id: np.ndarray
    sonar_cm: np.ndarray
    accel_ms2: np.ndarray
    gyro_rads: np.ndarray
    label: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SVG figures for DETECTION_ALGORITHM_DESIGN.md"
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Optional measured CSV. Required columns are documented in the design.",
    )
    parser.add_argument(
        "--buoy-id",
        help="Buoy ID to plot from a multi-buoy CSV. Defaults to the first sorted ID.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "assets" / "detection",
        help="Directory for generated SVG files.",
    )
    return parser.parse_args()


def load_csv(path: Path) -> Measurements:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no data rows")

    timestamp_ms = np.asarray([float(row["timestamp_ms"]) for row in rows])
    labels = np.asarray([row["label"].strip().upper() for row in rows])
    unknown = sorted(set(labels) - set(LABELS))
    if unknown:
        raise ValueError(f"CSV contains unknown labels: {unknown}")

    order = np.argsort(timestamp_ms)
    timestamp_ms = timestamp_ms[order]
    return Measurements(
        time_s=(timestamp_ms - timestamp_ms[0]) / 1000.0,
        buoy_id=np.asarray([row["buoy_id"] for row in rows])[order],
        sonar_cm=np.asarray([float(row["sonar_cm"]) for row in rows])[order],
        accel_ms2=np.asarray([float(row["accel_mag_ms2"]) for row in rows])[order],
        gyro_rads=np.asarray([float(row["gyro_mag_rads"]) for row in rows])[order],
        label=labels[order],
    )


def select_buoy(data: Measurements, requested_id: str | None) -> Measurements:
    available = sorted(set(data.buoy_id))
    buoy_id = requested_id or available[0]
    if buoy_id not in available:
        raise ValueError(f"Unknown buoy ID {buoy_id!r}; available IDs: {available}")
    selected = data.buoy_id == buoy_id
    print(f"Using buoy ID {buoy_id!r} from measured CSV")
    return Measurements(
        time_s=data.time_s[selected],
        buoy_id=data.buoy_id[selected],
        sonar_cm=data.sonar_cm[selected],
        accel_ms2=data.accel_ms2[selected],
        gyro_rads=data.gyro_rads[selected],
        label=data.label[selected],
    )


def synthetic_measurements() -> Measurements:
    rng = np.random.default_rng(SEED)
    time_s = np.arange(0.0, 90.0, 0.1)
    label = np.full(time_s.shape, "CALM", dtype="<U18")
    label[(time_s >= 25) & (time_s < 50)] = "ENVIRONMENTAL_WAVE"
    label[(time_s >= 60) & (time_s < 78)] = "DUMMY_SPLASH"

    sonar = 82.0 + rng.normal(0, 0.18, time_s.size)
    accel = 9.81 + rng.normal(0, 0.025, time_s.size)
    gyro = np.abs(rng.normal(0, 0.008, time_s.size))

    wave = label == "ENVIRONMENTAL_WAVE"
    sonar[wave] += 2.4 * np.sin(2 * np.pi * 0.32 * time_s[wave])
    accel[wave] += 0.85 * np.sin(2 * np.pi * 0.32 * time_s[wave] + 0.5)
    gyro[wave] += 0.24 * np.abs(np.sin(2 * np.pi * 0.32 * time_s[wave]))

    splash = label == "DUMMY_SPLASH"
    pulse = np.maximum(0, np.sin(2 * np.pi * 1.35 * time_s[splash]))
    sonar[splash] += 5.8 * pulse + rng.normal(0, 1.15, splash.sum())
    accel[splash] += 0.16 * np.sin(2 * np.pi * 0.7 * time_s[splash])
    gyro[splash] += 0.035 * np.abs(np.sin(2 * np.pi * 0.7 * time_s[splash]))

    return Measurements(
        time_s=time_s,
        buoy_id=np.full(time_s.shape, "B", dtype="<U8"),
        sonar_cm=sonar,
        accel_ms2=accel,
        gyro_rads=gyro,
        label=label,
    )


def add_data_notice(fig: plt.Figure, synthetic: bool) -> None:
    text = "Illustrative synthetic data" if synthetic else "Measured CSV data"
    color = "#9d0208" if synthetic else "#1b4332"
    fig.text(
        0.995,
        0.005,
        text,
        ha="right",
        va="bottom",
        fontsize=9,
        color=color,
        weight="bold",
    )


def save_figure(fig: plt.Figure, output_dir: Path, name: str, synthetic: bool) -> None:
    add_data_notice(fig, synthetic)
    fig.savefig(
        output_dir / name,
        format="svg",
        bbox_inches="tight",
        metadata={"Date": None},
    )
    plt.close(fig)


def rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    result = np.empty_like(values, dtype=float)
    radius = window // 2
    for index in range(values.size):
        lo = max(0, index - radius)
        hi = min(values.size, index + radius + 1)
        result[index] = np.median(values[lo:hi])
    return result


def hampel_filter(values: np.ndarray, window: int = 7, threshold: float = 3.5) -> tuple[np.ndarray, np.ndarray]:
    filtered = values.astype(float).copy()
    outlier = np.zeros(values.size, dtype=bool)
    radius = window // 2
    for index in range(values.size):
        lo = max(0, index - radius)
        hi = min(values.size, index + radius + 1)
        local = values[lo:hi]
        median = np.median(local)
        mad = np.median(np.abs(local - median))
        robust_sigma = max(1.4826 * mad, 1e-6)
        if abs(values[index] - median) > threshold * robust_sigma:
            filtered[index] = median
            outlier[index] = True
    return filtered, outlier


def rolling_stat(values: np.ndarray, window: int, fn) -> np.ndarray:
    result = np.empty_like(values, dtype=float)
    for index in range(values.size):
        lo = max(0, index - window + 1)
        result[index] = fn(values[lo : index + 1])
    return result


def robust_z(values: np.ndarray, baseline_mask: np.ndarray) -> np.ndarray:
    baseline = values[baseline_mask]
    if baseline.size < 5:
        baseline = values
    median = np.median(baseline)
    mad = np.median(np.abs(baseline - median))
    sigma = max(1.4826 * mad, np.std(baseline), 1e-6)
    return np.maximum(0.0, (np.abs(values - median) / sigma) - 1.0)


def rolling_rms(values: np.ndarray, window: int) -> np.ndarray:
    squared = rolling_stat(values**2, window, np.mean)
    return np.sqrt(squared)


def derive_scores(data: Measurements) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sonar_center = rolling_median(data.sonar_cm, 21)
    sonar_residual = data.sonar_cm - sonar_center
    accel_residual = data.accel_ms2 - 9.81
    baseline = np.isin(data.label, ["CALM", "ENVIRONMENTAL_WAVE"])

    sample_step = max(float(np.median(np.diff(data.time_s))), 0.02)
    window = max(3, round(2.0 / sample_step))
    sonar_feature = rolling_rms(sonar_residual, window)
    accel_feature = rolling_rms(accel_residual, window)
    gyro_feature = rolling_rms(data.gyro_rads, window)

    disturbance = np.clip(22.0 * robust_z(sonar_feature, baseline), 0, 100)
    motion = np.clip(
        14.0
        * np.maximum(
            robust_z(accel_feature, baseline),
            robust_z(gyro_feature, baseline),
        ),
        0,
        100,
    )
    local = np.clip(0.75 * disturbance + 0.25 * np.maximum(0, disturbance - motion), 0, 100)
    return disturbance, motion, local


def representative_by_label(data: Measurements, label: str, seconds: float = 16.0) -> Measurements:
    indices = np.flatnonzero(data.label == label)
    if indices.size == 0:
        return synthetic_measurements_for_label(label, seconds)
    start = indices[0]
    end_time = data.time_s[start] + seconds
    chosen = indices[data.time_s[indices] <= end_time]
    if chosen.size < 10:
        chosen = indices
    return Measurements(
        time_s=data.time_s[chosen] - data.time_s[chosen][0],
        buoy_id=data.buoy_id[chosen],
        sonar_cm=data.sonar_cm[chosen],
        accel_ms2=data.accel_ms2[chosen],
        gyro_rads=data.gyro_rads[chosen],
        label=data.label[chosen],
    )


def synthetic_measurements_for_label(label: str, seconds: float) -> Measurements:
    source = synthetic_measurements()
    selected = source.label == label
    result = representative_by_label(source, label, seconds)
    if selected.sum() == 0:
        raise ValueError(f"Cannot synthesize unknown label {label}")
    return result


def graph_signal_comparison(data: Measurements, output_dir: Path, synthetic: bool) -> None:
    figure_is_synthetic = synthetic or any(np.sum(data.label == label) < 10 for label in ("CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH"))
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex="col")
    for column, label in enumerate(("CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH")):
        segment = representative_by_label(data, label)
        axes[column, 0].plot(segment.time_s, segment.sonar_cm, color=COLORS[label], lw=1.4)
        axes[column, 1].plot(segment.time_s, segment.accel_ms2, color=COLORS[label], lw=1.4)
        axes[column, 0].set_ylabel(label)
        axes[column, 0].grid(alpha=0.25)
        axes[column, 1].grid(alpha=0.25)
    axes[0, 0].set_title("Sonar distance")
    axes[0, 1].set_title("Buoy acceleration magnitude")
    axes[-1, 0].set_xlabel("Time (s)")
    axes[-1, 1].set_xlabel("Time (s)")
    axes[1, 0].set_ylabel("ENVIRONMENTAL\nWAVE")
    fig.suptitle("Signal signatures: calm, common wave, and local dummy splash", weight="bold")
    fig.tight_layout()
    save_figure(fig, output_dir, "01_signal_comparison.svg", figure_is_synthetic)


def graph_hampel(data: Measurements, output_dir: Path, synthetic: bool) -> None:
    rng = np.random.default_rng(SEED + 1)
    segment = representative_by_label(data, "CALM", seconds=22)
    values = segment.sonar_cm.copy()
    figure_is_synthetic = synthetic or values.size < 30
    if figure_is_synthetic:
        values = 82 + rng.normal(0, 0.2, 220)
        time_s = np.arange(values.size) / 10
        positions = (np.linspace(0.2, 0.85, 4) * (values.size - 1)).astype(int)
        values[positions] += np.asarray([8, -11, 14, -9])
    else:
        time_s = segment.time_s
    filtered, outlier = hampel_filter(values)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(time_s, values, color="#5c677d", label="Raw sonar")
    axes[0].scatter(time_s[outlier], values[outlier], color=COLORS["SENSOR_FAULT"], label="Detected spike", zorder=3)
    axes[0].set_title("Before Hampel filtering")
    axes[1].plot(time_s, filtered, color=COLORS["CALM"], label="Baseline input after replacement")
    axes[1].scatter(time_s[outlier], filtered[outlier], facecolors="none", edgecolors=COLORS["SENSOR_FAULT"], label="Replaced by local median")
    axes[1].set_title("Baseline-learning path after filtering")
    for axis in axes:
        axis.set_ylabel("Sonar (cm)")
        axis.grid(alpha=0.25)
        axis.legend(loc="upper right")
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("A single sensor spike is removed only from the baseline-learning path", weight="bold")
    fig.tight_layout()
    save_figure(fig, output_dir, "02_hampel_filter.svg", figure_is_synthetic)


def graph_baseline_outlier(data: Measurements, output_dir: Path, synthetic: bool) -> None:
    rng = np.random.default_rng(SEED + 2)
    minute_index = np.floor(data.time_s / 60).astype(int)
    measured_values = np.asarray(
        [
            np.std(data.sonar_cm[minute_index == index])
            for index in sorted(set(minute_index))
            if np.sum(minute_index == index) >= 10
        ]
    )
    figure_is_synthetic = synthetic or measured_values.size < 10
    if figure_is_synthetic:
        values = 4.0 + 0.4 * np.sin(np.linspace(0, 5 * np.pi, 120)) + rng.normal(0, 0.25, 120)
        values[70:73] = [18, 23, 16]
    else:
        values = measured_values
    window = min(20, max(3, values.size // 5))
    moving_mean = rolling_stat(values, window, np.mean)
    rolling_med = rolling_stat(values, window, np.median)
    rolling_mad = rolling_stat(values, window, lambda x: 1.4826 * np.median(np.abs(x - np.median(x))))

    fig, axis = plt.subplots(figsize=(12, 6))
    time_min = np.arange(values.size)
    axis.plot(time_min, values, color="#adb5bd", lw=1, label="60 s feature summary")
    axis.plot(time_min, moving_mean, color="#f4a261", lw=2, label="Moving mean")
    axis.plot(time_min, rolling_med, color="#2a9d8f", lw=2, label="Rolling median")
    axis.fill_between(
        time_min,
        rolling_med - rolling_mad,
        rolling_med + rolling_mad,
        color="#2a9d8f",
        alpha=0.16,
        label="Median +/- robust scale",
    )
    if figure_is_synthetic:
        axis.axvspan(70, 72, color=COLORS["SENSOR_FAULT"], alpha=0.13, label="Outlier interval")
    axis.set_xlabel("Rolling summary index (1 per minute)")
    axis.set_ylabel("Example feature value")
    axis.set_title("Moving mean drifts after outliers; median/MAD stays stable", weight="bold")
    axis.grid(alpha=0.25)
    axis.legend(ncol=2)
    fig.tight_layout()
    save_figure(fig, output_dir, "03_robust_baseline.svg", figure_is_synthetic)


def graph_decision_regions(output_dir: Path) -> None:
    disturbance = np.linspace(0, 100, 201)
    motion = np.linspace(0, 100, 201)
    xx, yy = np.meshgrid(disturbance, motion)
    local = np.clip(0.75 * xx + 0.25 * np.maximum(0, xx - yy), 0, 100)
    regions = np.where(local >= 70, 2, np.where(local >= 55, 1, 0))

    fig, axis = plt.subplots(figsize=(9, 7))
    axis.contourf(
        xx,
        yy,
        regions,
        levels=[-0.5, 0.5, 1.5, 2.5],
        colors=["#d8f3dc", "#ffe8a1", "#ffb4a2"],
        alpha=0.85,
    )
    contours = axis.contour(xx, yy, local, levels=[40, 55, 70], colors=["#6c757d", "#e9c46a", "#d00000"])
    axis.clabel(contours, inline=True, fmt="score %d")
    axis.scatter([82], [18], color=COLORS["DUMMY_SPLASH"], s=90, label="Local dummy splash example")
    axis.scatter([70], [78], color=COLORS["ENVIRONMENTAL_WAVE"], s=90, label="Common wave example")
    axis.set_xlabel("Disturbance score")
    axis.set_ylabel("Buoy motion score")
    axis.set_title("Initial decision regions before lake-data tuning", weight="bold")
    axis.grid(alpha=0.2)
    axis.legend(loc="upper left")
    fig.tight_layout()
    save_figure(fig, output_dir, "04_decision_regions.svg", True)


def graph_multi_buoy(output_dir: Path) -> None:
    rng = np.random.default_rng(SEED + 3)
    time_s = np.arange(0, 45)
    common = 18 + rng.normal(0, 2, (3, time_s.size))
    common[:, 12:28] += np.asarray([[42], [47], [44]]) + rng.normal(0, 3, (3, 16))
    local = 15 + rng.normal(0, 2, (3, time_s.size))
    local[1, 12:28] += 70 + rng.normal(0, 4, 16)
    local[0, 12:28] += 6
    local[2, 12:28] += 8

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for index, name in enumerate(("Buoy A", "Buoy B", "Buoy C")):
        axes[0].plot(time_s, common[index], label=name)
        axes[1].plot(time_s, local[index], label=name)
    axes[0].set_title("Environmental wave: multiple buoys react")
    axes[1].set_title("Local dummy splash: one buoy dominates")
    for axis in axes:
        axis.axhline(55, color="#e9c46a", ls="--", label="SUSPECT threshold")
        axis.axhline(70, color="#d00000", ls="--", label="ALERT threshold")
        axis.set_xlabel("Time (s)")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Local score")
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=5)
    fig.suptitle("Raspberry Pi compares buoy reactions within a short time window", weight="bold")
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    save_figure(fig, output_dir, "05_multi_buoy_comparison.svg", True)


def graph_state_timeline(data: Measurements, output_dir: Path, synthetic: bool) -> None:
    disturbance, motion, local = derive_scores(data)
    time_s = data.time_s
    if time_s.size > 1400:
        select = np.linspace(0, time_s.size - 1, 1400).astype(int)
        time_s = time_s[select]
        disturbance = disturbance[select]
        motion = motion[select]
        local = local[select]

    state = np.zeros(local.size)
    suspect_hits: list[bool] = []
    alert_hits: list[bool] = []
    current = 0
    for index, score in enumerate(local):
        suspect_hits.append(score >= 55)
        alert_hits.append(score >= 70)
        suspect_count = sum(suspect_hits[-5:])
        alert_count = sum(alert_hits[-8:])
        if alert_count >= 3:
            current = 2
        elif suspect_count >= 2:
            current = max(current, 1)
        elif score < 40:
            current = 0
        state[index] = current

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    axes[0].plot(time_s, disturbance, label="Disturbance score", color=COLORS["DUMMY_SPLASH"])
    axes[0].plot(time_s, motion, label="Motion score", color=COLORS["ENVIRONMENTAL_WAVE"])
    axes[0].plot(time_s, local, label="Local score", color="#212529", lw=1.8)
    axes[0].axhline(55, color="#e9c46a", ls="--", label="SUSPECT threshold")
    axes[0].axhline(70, color="#d00000", ls="--", label="ALERT threshold")
    axes[0].set_ylabel("Score")
    axes[0].set_ylim(0, 105)
    axes[0].grid(alpha=0.25)
    axes[0].legend(ncol=3)

    axes[1].step(time_s, state, where="post", color="#343a40", lw=2)
    axes[1].fill_between(time_s, 0, state, step="post", color="#ffb4a2", alpha=0.5)
    axes[1].set_yticks([0, 1, 2], ["NORMAL", "SUSPECT", "ALERT"])
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("State")
    axes[1].grid(alpha=0.25)
    fig.suptitle("Example score accumulation and state transition", weight="bold")
    fig.tight_layout()
    save_figure(fig, output_dir, "06_state_timeline.svg", synthetic)


def configure_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "svg.fonttype": "none",
            "svg.hashsalt": "lora-detection-design",
        }
    )


def main() -> None:
    args = parse_args()
    configure_plot_style()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    synthetic = args.csv is None
    data = synthetic_measurements() if synthetic else select_buoy(load_csv(args.csv), args.buoy_id)

    graph_signal_comparison(data, args.output_dir, synthetic)
    graph_hampel(data, args.output_dir, synthetic)
    graph_baseline_outlier(data, args.output_dir, synthetic)
    graph_decision_regions(args.output_dir)
    graph_multi_buoy(args.output_dir)
    graph_state_timeline(data, args.output_dir, synthetic)

    print(f"Generated 6 SVG graphs in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
