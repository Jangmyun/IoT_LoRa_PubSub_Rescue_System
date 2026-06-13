import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rescue_detection_ml.features import DetectionFeatureConfig, build_feature_table  # noqa: E402
from rescue_detection_ml.modeling import predict_feature_table, train_candidate_models  # noqa: E402
from rescue_detection_ml.synthetic import make_synthetic_measurements  # noqa: E402


class ModelingTests(unittest.TestCase):
    def test_trains_candidates_and_saves_joblib_bundle(self):
        raw = make_synthetic_measurements(minutes=9.0)
        config = DetectionFeatureConfig(min_baseline_windows=3)
        features = build_feature_table(raw, config)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = train_candidate_models(features, tmpdir, feature_config=config.to_dict())

            self.assertIn(
                result.best_model_name,
                {"decision_tree", "random_forest", "hist_gradient_boosting"},
            )
            self.assertTrue((Path(tmpdir) / "model.joblib").exists())
            self.assertTrue((Path(tmpdir) / "metrics.csv").exists())
            self.assertEqual(set(result.metrics["model"]), {
                "decision_tree",
                "random_forest",
                "hist_gradient_boosting",
            })
            self.assertEqual(result.bundle["feature_config"]["window_seconds"], 2.0)

    def test_prediction_keeps_rule_based_sensor_fault(self):
        raw = make_synthetic_measurements(minutes=9.0)
        features = build_feature_table(raw, DetectionFeatureConfig(min_baseline_windows=3))

        with tempfile.TemporaryDirectory() as tmpdir:
            result = train_candidate_models(features, tmpdir)
            predictions = predict_feature_table(result.bundle, features)

        fault_predictions = predictions[predictions["rule_label"] == "SENSOR_FAULT"]
        self.assertGreater(len(fault_predictions), 0)
        self.assertTrue((fault_predictions["predicted_label"] == "SENSOR_FAULT").all())
        self.assertTrue(predictions["predicted_label"].ne("").all())


if __name__ == "__main__":
    unittest.main()
