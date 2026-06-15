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
from rescue_detection_ml.features import ACCEL_FEATURE_COLUMNS  # noqa: E402
from state import TOPIC_SENSOR_RAW  # noqa: E402


class FakeModel:
    classes_ = ["CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH"]

    def predict(self, rows):
        return ["DUMMY_SPLASH"] * len(rows)

    def predict_proba(self, rows):
        return [[0.05, 0.10, 0.85] for _ in range(len(rows))]


class AmbiguousWaveModel:
    classes_ = ["CALM", "ENVIRONMENTAL_WAVE", "DUMMY_SPLASH"]

    def predict(self, rows):
        return ["ENVIRONMENTAL_WAVE"] * len(rows)

    def predict_proba(self, rows):
        return [[0.20, 0.45, 0.35] for _ in range(len(rows))]


class LiveMlClassifierTests(unittest.TestCase):
    def test_missing_model_path_disables_classifier_without_crashing(self):
        classifier = LiveMlClassifier(model_path="/tmp/does-not-exist/model.joblib")

        self.assertFalse(classifier.enabled)
        self.assertEqual(classifier.status()["enabled"], False)
        self.assertEqual(classifier.status()["suspect_threshold"], 0.30)

    def test_predicts_latest_sensor_window_and_maps_alert_status(self):
        classifier = LiveMlClassifier(
            bundle={
                "model": FakeModel(),
                "feature_columns": ACCEL_FEATURE_COLUMNS,
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
        self.assertEqual(prediction.risk, "POSSIBLE_VICTIM")
        self.assertEqual(prediction.confidence, 85)
        self.assertEqual(prediction.victim_probability, 85)
        self.assertEqual(prediction.status, "SUSPECT")

    def test_maps_ambiguous_victim_probability_to_suspect_status(self):
        classifier = LiveMlClassifier(
            bundle={
                "model": AmbiguousWaveModel(),
                "feature_columns": ACCEL_FEATURE_COLUMNS,
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

        for index, accel in enumerate([10.8, 11.1, 12.0, 11.7]):
            packet = {
                "node_id": 2,
                "topic": TOPIC_SENSOR_RAW,
            }
            state = {
                "sonar_cm": 42,
                "accel_ms2": accel,
            }
            prediction = classifier.add_packet(packet, state, start + timedelta(seconds=3 * index))

        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.label, "ENVIRONMENTAL_WAVE")
        self.assertEqual(prediction.confidence, 45)
        self.assertEqual(prediction.victim_probability, 35)
        self.assertEqual(prediction.status, "SUSPECT")

    def test_high_threshold_keeps_ambiguous_wave_normal(self):
        classifier = LiveMlClassifier(
            bundle={
                "model": AmbiguousWaveModel(),
                "feature_columns": ACCEL_FEATURE_COLUMNS,
                "feature_config": {
                    "window_seconds": 10.0,
                    "stride_seconds": 5.0,
                    "min_samples_per_window": 3,
                    "min_baseline_windows": 3,
                },
            },
            suspect_threshold=0.40,
        )
        start = datetime(2026, 6, 14, 12, 0, 0)
        prediction = None

        for index, accel in enumerate([10.8, 11.1, 12.0, 11.7]):
            packet = {
                "node_id": 2,
                "topic": TOPIC_SENSOR_RAW,
            }
            state = {
                "sonar_cm": 42,
                "accel_ms2": accel,
            }
            prediction = classifier.add_packet(packet, state, start + timedelta(seconds=3 * index))

        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.victim_probability, 35)
        self.assertEqual(prediction.status, "NORMAL")
        self.assertEqual(classifier.status()["suspect_threshold"], 0.40)


if __name__ == "__main__":
    unittest.main()
