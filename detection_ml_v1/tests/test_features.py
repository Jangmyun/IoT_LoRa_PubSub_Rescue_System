import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rescue_detection_ml.features import (  # noqa: E402
    FEATURE_COLUMNS,
    DetectionFeatureConfig,
    build_feature_table,
)


class FeatureExtractionTests(unittest.TestCase):
    def test_builds_requested_features_from_raw_samples(self):
        timestamps = np.arange(0, 12_000, 100)
        labels = np.where(timestamps < 8_000, "CALM", "DUMMY_SPLASH")
        sonar = np.full(timestamps.shape, 82.0, dtype=float)
        sonar[timestamps >= 8_000] += 5.0 * np.sin(2 * np.pi * 1.5 * timestamps[timestamps >= 8_000] / 1000.0)
        accel = np.full(timestamps.shape, 9.80665, dtype=float)
        frame = pd.DataFrame(
            {
                "timestamp_ms": timestamps,
                "buoy_id": "A",
                "sonar_cm": sonar,
                "accel_mag_ms2": accel,
                "label": labels,
            }
        )
        config = DetectionFeatureConfig(min_baseline_windows=3)

        features = build_feature_table(frame, config)

        self.assertGreater(len(features), 0)
        for column in FEATURE_COLUMNS:
            self.assertIn(column, features.columns)
        splash = features[features["label"] == "DUMMY_SPLASH"]
        self.assertGreater(splash["sonar_rms_2s"].max(), 1.0)
        self.assertGreater(splash["sonar_z"].max(), 0.0)

    def test_sensor_fault_is_rule_based_before_ml(self):
        frame = pd.DataFrame(
            {
                "timestamp_ms": np.arange(0, 2_000, 100),
                "buoy_id": "A",
                "sonar_cm": [np.nan, 999.0, 82.0, 83.0] * 5,
                "accel_mag_ms2": [9.8] * 20,
                "label": ["CALM"] * 20,
            }
        )

        features = build_feature_table(frame, DetectionFeatureConfig(min_samples_per_window=3))

        self.assertEqual(features.iloc[0]["rule_label"], "SENSOR_FAULT")
        self.assertEqual(features.iloc[0]["label"], "SENSOR_FAULT")
        self.assertGreaterEqual(features.iloc[0]["fault_rate"], 0.25)

    def test_missing_required_columns_raise_clear_error(self):
        frame = pd.DataFrame({"timestamp_ms": [0], "sonar_cm": [82.0]})

        with self.assertRaisesRegex(ValueError, "Missing required columns"):
            build_feature_table(frame)

    def test_unlabeled_collection_rows_are_allowed_for_prediction(self):
        frame = pd.DataFrame(
            {
                "timestamp_ms": np.arange(0, 2_000, 100),
                "buoy_id": "A",
                "sonar_cm": [82.0] * 20,
                "accel_mag_ms2": [9.80665] * 20,
                "label": [""] * 20,
            }
        )

        features = build_feature_table(frame, DetectionFeatureConfig(min_samples_per_window=3))

        self.assertEqual(features.iloc[0]["label"], "")


if __name__ == "__main__":
    unittest.main()
