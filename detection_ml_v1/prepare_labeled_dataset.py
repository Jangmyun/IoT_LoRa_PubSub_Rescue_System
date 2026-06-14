#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd

from collect_serial_csv import CSV_COLUMNS, parse_csv_line
from rescue_detection_ml.features import LABELS


LABEL_ALIASES = {
    "0": "CALM",
    "1": "ENVIRONMENTAL_WAVE",
    "2": "DUMMY_SPLASH",
    "3": "SENSOR_FAULT",
    **{label: label for label in LABELS},
}


def parse_run_spec(spec: str) -> tuple[Path, str, str | None]:
    if "=" not in spec:
        raise ValueError("Run spec must be PATH=LABEL, for example csv_result_1.csv=CALM")
    path_text, label_text = spec.split("=", 1)
    label_part, buoy_id = _split_label_and_buoy(label_text)
    label = LABEL_ALIASES.get(label_part.strip().upper())
    if not label:
        raise ValueError(f"Unknown label {label_part!r}; use one of {sorted(LABEL_ALIASES)}")
    return Path(path_text), label, buoy_id


def _split_label_and_buoy(label_text: str) -> tuple[str, str | None]:
    if "@" not in label_text:
        return label_text, None
    label, buoy_id = label_text.split("@", 1)
    buoy_id = buoy_id.strip()
    if not buoy_id:
        raise ValueError("Run buoy filter must not be empty; use PATH=LABEL@BUOY_ID")
    return label, buoy_id


def load_collection_csv(path: Path, label: str) -> pd.DataFrame:
    """Load either a normal CSV file or raw firmware log containing CSV-prefixed lines."""

    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        first = handle.readline()
        handle.seek(0)
        if first.startswith("timestamp_ms,"):
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append(_normalize_row(row, label))
        else:
            for line in handle:
                row = parse_csv_line(line, label)
                if row is not None:
                    rows.append(_normalize_row(row, label))

    if not rows:
        raise ValueError(f"No sensor rows found in {path}")
    return pd.DataFrame(rows, columns=CSV_COLUMNS)


def trim_by_elapsed_seconds(
    frame: pd.DataFrame,
    trim_start_seconds: float,
    trim_end_seconds: float,
) -> pd.DataFrame:
    out = frame.copy()
    timestamp = pd.to_numeric(out["timestamp_ms"], errors="coerce")
    elapsed = (timestamp - timestamp.min()) / 1000.0
    keep = elapsed >= trim_start_seconds
    if trim_end_seconds > 0:
        keep &= elapsed <= elapsed.max() - trim_end_seconds
    return out[keep].copy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge offline collection files and stamp labels for training."
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="Input mapping PATH=LABEL or PATH=LABEL@BUOY_ID. Numeric labels are 0,1,2,3.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--trim-start-seconds",
        type=float,
        default=0.0,
        help="Drop the first N seconds from every run.",
    )
    parser.add_argument(
        "--trim-end-seconds",
        type=float,
        default=0.0,
        help="Drop the last N seconds from every run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = []
    for spec in args.run:
        path, label, buoy_id = parse_run_spec(spec)
        frame = load_collection_csv(path, label)
        if buoy_id is not None:
            frame = filter_by_buoy_id(frame, buoy_id, path)
        frame = trim_by_elapsed_seconds(frame, args.trim_start_seconds, args.trim_end_seconds)
        frame["source_file"] = path.name
        frames.append(frame)

    merged = pd.concat(frames, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False)
    print(f"saved_rows={len(merged)}")
    print(f"output={args.output}")


def _normalize_row(row: dict[str, str], label: str) -> dict[str, str]:
    normalized = {column: str(row.get(column, "")).strip() for column in CSV_COLUMNS}
    normalized["label"] = label
    return normalized


def filter_by_buoy_id(frame: pd.DataFrame, buoy_id: str, path: Path) -> pd.DataFrame:
    filtered = frame[frame["buoy_id"].astype(str) == str(buoy_id)].copy()
    if filtered.empty:
        available = sorted(frame["buoy_id"].astype(str).unique())
        raise ValueError(f"No rows for buoy_id={buoy_id!r} in {path}; available={available}")
    return filtered


if __name__ == "__main__":
    main()
