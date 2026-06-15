import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

original_cwd = os.getcwd()
os.chdir(SERVER_DIR)
import main as server_main  # noqa: E402
from ml_inference import LiveMlClassifier  # noqa: E402
from state import TOPIC_SENSOR_RAW  # noqa: E402
os.chdir(original_cwd)


NOW = datetime(2026, 6, 15, 16, 0, 0)


class ServerRuleTests(unittest.TestCase):
    def setUp(self):
        self.previous_classifier = server_main.ml_classifier
        server_main.ml_classifier = LiveMlClassifier.disabled()
        server_main.buoy_states.clear()
        server_main.event_history.clear()

    def tearDown(self):
        server_main.ml_classifier = self.previous_classifier
        server_main.buoy_states.clear()
        server_main.event_history.clear()

    def test_sonar_distance_at_threshold_promotes_sensor_packet_to_suspect(self):
        state, event = server_main.apply_packet(_sensor_packet(25), NOW)

        self.assertEqual(state["status"], "SUSPECT")
        self.assertTrue(state["sonar_rule_triggered"])
        self.assertEqual(state["sonar_rule_label"], "NEAR_OBJECT")
        self.assertEqual(state["sonar_rule_threshold_cm"], 25)
        self.assertEqual(state["alert_confidence"], 100)
        self.assertEqual(event["level"], "SUSPECT")
        self.assertIn("sonar<=", event["text"])

    def test_sonar_distance_above_threshold_clears_previous_sonar_warning(self):
        server_main.apply_packet(_sensor_packet(25), NOW)

        state, _ = server_main.apply_packet(_sensor_packet(26), NOW)

        self.assertEqual(state["status"], "NORMAL")
        self.assertFalse(state["sonar_rule_triggered"])
        self.assertEqual(state["sonar_rule_label"], "")
        self.assertEqual(state["alert_confidence"], 0)

    def test_sonar_clear_does_not_hide_active_ml_suspect_status(self):
        state = {
            "status": "SUSPECT",
            "sonar_cm": 30,
            "sonar_rule_triggered": True,
            "ml_status": "SUSPECT",
            "alert_confidence": 35,
        }

        triggered = server_main.apply_sonar_distance_rule(_sensor_packet(30), state)

        self.assertFalse(triggered)
        self.assertEqual(state["status"], "SUSPECT")
        self.assertEqual(state["alert_confidence"], 35)


def _sensor_packet(sonar_cm: int) -> dict:
    return {
        "node_id": 2,
        "msg_type": "PUBLISH",
        "topic": TOPIC_SENSOR_RAW,
        "ttl": 3,
        "payload": [sonar_cm, 110],
    }


if __name__ == "__main__":
    unittest.main()
