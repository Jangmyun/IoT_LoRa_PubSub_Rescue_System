import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluate_test_set import (  # noqa: E402
    compute_binary_metrics,
    compute_multiclass_metrics,
    default_run_specs,
)


class EvaluateTestSetTests(unittest.TestCase):
    def test_default_run_specs_label_requested_test_files(self):
        specs = default_run_specs(Path("detection_ml_v1/test"))

        self.assertEqual(
            specs,
            [
                "detection_ml_v1/test/csv_result_001.csv=CALM",
                "detection_ml_v1/test/csv_result_002.csv=ENVIRONMENTAL_WAVE",
                "detection_ml_v1/test/csv_result_003.csv=ENVIRONMENTAL_WAVE",
                "detection_ml_v1/test/csv_result_004.csv=DUMMY_SPLASH",
            ],
        )

    def test_binary_metrics_count_false_positive_and_false_negative(self):
        frame = pd.DataFrame(
            {
                "actual_victim": [False, False, True, True],
                "predicted_alert": [False, True, False, True],
            }
        )

        metrics = compute_binary_metrics(frame).iloc[0]

        self.assertEqual(metrics["tn"], 1)
        self.assertEqual(metrics["fp"], 1)
        self.assertEqual(metrics["fn"], 1)
        self.assertEqual(metrics["tp"], 1)
        self.assertEqual(metrics["accuracy"], 0.5)
        self.assertEqual(metrics["false_negative_rate"], 0.5)
        self.assertEqual(metrics["false_positive_rate"], 0.5)

    def test_multiclass_metrics_include_overall_row(self):
        frame = pd.DataFrame(
            {
                "label": ["CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH"],
                "predicted_label": ["CALM", "DUMMY_SPLASH", "DUMMY_SPLASH"],
            }
        )

        metrics = compute_multiclass_metrics(frame)

        self.assertIn("overall", set(metrics["label"]))
        self.assertEqual(metrics.loc[metrics["label"].eq("CALM"), "recall"].iloc[0], 1.0)
        self.assertEqual(metrics.loc[metrics["label"].eq("ENVIRONMENTAL_WAVE"), "recall"].iloc[0], 0.0)


if __name__ == "__main__":
    unittest.main()
