#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from rescue_detection_ml.synthetic import make_synthetic_measurements


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic demo CSV for v1 ML pipeline.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("detection_ml_v1/example_data/synthetic_measurements.csv"),
    )
    parser.add_argument("--minutes", type=float, default=12.0)
    parser.add_argument("--sample-hz", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = make_synthetic_measurements(minutes=args.minutes, sample_hz=args.sample_hz)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(args.output, index=False)
    print(f"saved_rows={len(data)}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
