#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from rescue_detection_ml.features import LABELS


CSV_PREFIX = "CSV,"
CSV_COLUMNS = [
    "timestamp_ms",
    "buoy_id",
    "sonar_cm",
    "accel_mag_ms2",
    "sonar_valid",
    "sonar_timeout",
    "label",
]


def parse_csv_line(line: str, label: str = "") -> dict[str, str] | None:
    """Parse one firmware CSV line and ignore non-data log lines."""

    text = line.strip()
    if not text.startswith(CSV_PREFIX):
        return None

    payload = text[len(CSV_PREFIX) :]
    if payload.startswith("timestamp_ms,"):
        return None

    values = next(csv.reader([payload]))
    if len(values) < 6:
        return None
    if len(values) == 6:
        values.append("")

    row = dict(zip(CSV_COLUMNS, values[: len(CSV_COLUMNS)]))
    if label:
        row["label"] = label
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect firmware CSV lines from a TTGO serial port."
    )
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--label",
        choices=LABELS,
        default="",
        help="Optional label to stamp on all collected rows for one scenario.",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=0.0,
        help="Stop after N seconds. Use 0 to collect until Ctrl+C.",
    )
    return parser.parse_args()


def main() -> None:
    import serial

    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stop_at = time.monotonic() + args.seconds if args.seconds > 0 else None
    rows = 0

    with serial.Serial(args.port, args.baud, timeout=1) as ser:
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            try:
                while stop_at is None or time.monotonic() < stop_at:
                    raw = ser.readline()
                    if not raw:
                        continue
                    row = parse_csv_line(raw.decode("utf-8", errors="replace"), args.label)
                    if row is None:
                        continue
                    writer.writerow(row)
                    rows += 1
            except KeyboardInterrupt:
                pass

    print(f"saved_rows={rows}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
