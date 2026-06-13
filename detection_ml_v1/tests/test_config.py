import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rescue_detection_ml.config import resolve_feature_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_fast_serial_samples_use_two_second_window(self):
        raw = pd.DataFrame(
            {
                "timestamp_ms": [0, 100, 200, 300],
                "buoy_id": ["A"] * 4,
            }
        )

        config, sample_seconds, auto_selected = resolve_feature_config(raw)

        self.assertTrue(auto_selected)
        self.assertAlmostEqual(sample_seconds, 0.1)
        self.assertEqual(config.window_seconds, 2.0)
        self.assertEqual(config.stride_seconds, 1.0)

    def test_sparse_lora_samples_use_ten_second_window(self):
        raw = pd.DataFrame(
            {
                "timestamp_ms": [0, 3000, 6000, 9000],
                "buoy_id": ["A"] * 4,
            }
        )

        config, sample_seconds, auto_selected = resolve_feature_config(raw)

        self.assertTrue(auto_selected)
        self.assertAlmostEqual(sample_seconds, 3.0)
        self.assertEqual(config.window_seconds, 10.0)
        self.assertEqual(config.stride_seconds, 5.0)

    def test_explicit_window_and_stride_are_preserved(self):
        raw = pd.DataFrame(
            {
                "timestamp_ms": [0, 3000, 6000, 9000],
                "buoy_id": ["A"] * 4,
            }
        )

        config, _, auto_selected = resolve_feature_config(raw, window_seconds=6.0, stride_seconds=3.0)

        self.assertFalse(auto_selected)
        self.assertEqual(config.window_seconds, 6.0)
        self.assertEqual(config.stride_seconds, 3.0)


if __name__ == "__main__":
    unittest.main()
