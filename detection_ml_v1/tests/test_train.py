import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rescue_detection_ml.features import ACCEL_FEATURE_COLUMNS, FEATURE_COLUMNS  # noqa: E402
from train import resolve_feature_columns  # noqa: E402


class TrainCliTests(unittest.TestCase):
    def test_resolves_default_feature_set(self):
        self.assertEqual(resolve_feature_columns("default"), FEATURE_COLUMNS)

    def test_resolves_accel_only_feature_set_without_sonar_features(self):
        columns = resolve_feature_columns("accel")

        self.assertEqual(columns, ACCEL_FEATURE_COLUMNS)
        self.assertTrue(all(not column.startswith("sonar") for column in columns))


if __name__ == "__main__":
    unittest.main()
