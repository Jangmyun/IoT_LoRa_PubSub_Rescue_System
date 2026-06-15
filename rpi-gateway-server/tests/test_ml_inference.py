import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
REPO_ROOT = ROOT.parent
ML_DIR = REPO_ROOT / "detection_ml_v1"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(ML_DIR))

from ml_inference import LiveMlClassifier  # noqa: E402
from rescue_detection_ml.features import FEATURE_COLUMNS  # noqa: E402
from state import TOPIC_SENSOR_RAW  # noqa: E402


class FakeModel:
    def predict(self, rows):
        return ["DUMMY_SPLASH"] * len(rows)

    def predict_proba(self, rows):
        return [[0.05, 0.10, 0.85] for _ in range(len(rows))]


class LiveMlClassifierTests(unittest.TestCase):
    def test_missing_model_path_disables_classifier_without_crashing(self):
        classifier = LiveMlClassifier(model_path="/tmp/does-not-exist/model.joblib")

        self.assertFalse(classifier.enabled)
        self.assertEqual(classifier.status()["enabled"], False)

    def test_predicts_latest_sensor_window_and_maps_alert_status(self):
        classifier = LiveMlClassifier(
            bundle={
                "model": FakeModel(),
                "feature_columns": FEATURE_COLUMNS,
                "feature_config": {
                    "window_seconds": 10.0,
                    "stride_seconds": 5.0,
                    "min_samples_per_window": 3,
                    "min_baseline_windows": 3,
                },
            }
        )
        start = datetime(2026, 6, 14, 12, 0, 0)
        prediction = None

        for index, sonar in enumerate([20, 60, 120, 30]):
            packet = {
                "node_id": 2,
                "topic": TOPIC_SENSOR_RAW,
            }
            state = {
                "sonar_cm": sonar,
                "accel_ms2": 11.0,
            }
            prediction = classifier.add_packet(packet, state, start + timedelta(seconds=3 * index))

        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.label, "DUMMY_SPLASH")
        self.assertEqual(prediction.risk, "HIGH")
        self.assertEqual(prediction.confidence, 85)
        self.assertEqual(prediction.status, "ALERT")


if __name__ == "__main__":
    unittest.main()
