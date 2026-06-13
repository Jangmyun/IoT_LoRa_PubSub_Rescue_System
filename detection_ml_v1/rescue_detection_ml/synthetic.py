from __future__ import annotations

import numpy as np
import pandas as pd


def make_synthetic_measurements(
    minutes: float = 12.0,
    sample_hz: float = 10.0,
    seed: int = 20260613,
) -> pd.DataFrame:
    """Generate deterministic demo data until measured lake CSV exists."""

    rng = np.random.default_rng(seed)
    step_ms = int(1000 / sample_hz)
    timestamps = np.arange(0, int(minutes * 60 * 1000), step_ms)
    time_s = timestamps / 1000.0

    labels = np.full(timestamps.shape, "CALM", dtype="<U20")
    labels[(time_s >= 180) & (time_s < 300)] = "ENVIRONMENTAL_WAVE"
    labels[(time_s >= 390) & (time_s < 430)] = "DUMMY_SPLASH"
    labels[(time_s >= 510) & (time_s < 525)] = "SENSOR_FAULT"

    sonar = 82.0 + rng.normal(0, 0.15, timestamps.size)
    accel = 9.80665 + rng.normal(0, 0.025, timestamps.size)

    wave = labels == "ENVIRONMENTAL_WAVE"
    sonar[wave] += 2.5 * np.sin(2 * np.pi * 0.3 * time_s[wave])
    accel[wave] += 0.75 * np.sin(2 * np.pi * 0.3 * time_s[wave] + 0.4)

    splash = labels == "DUMMY_SPLASH"
    pulse = np.maximum(0, np.sin(2 * np.pi * 1.4 * time_s[splash]))
    sonar[splash] += 5.5 * pulse + rng.normal(0, 0.9, splash.sum())
    accel[splash] += 0.12 * np.sin(2 * np.pi * 0.8 * time_s[splash])

    fault = labels == "SENSOR_FAULT"
    sonar[fault] = np.where(np.arange(fault.sum()) % 2 == 0, np.nan, 999.0)
    accel[fault] = 9.80665

    return pd.DataFrame(
        {
            "timestamp_ms": timestamps,
            "buoy_id": "A",
            "sonar_cm": sonar,
            "accel_mag_ms2": accel,
            "label": labels,
        }
    )
