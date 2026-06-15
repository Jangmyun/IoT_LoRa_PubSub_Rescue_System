import unittest
from datetime import datetime

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from state import (
    TOPIC_ALERT,
    TOPIC_ALERT_CLEAR,
    TOPIC_HEARTBEAT,
    TOPIC_SENSOR_RAW,
    build_buoy_state,
)


NOW = datetime(2026, 6, 10, 12, 0, 0)


class StateTests(unittest.TestCase):
    def test_sensor_raw_decodes_packed_values(self):
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_SENSOR_RAW,
            "ttl": 3,
            "payload": [52, 124],
        }

        state = build_buoy_state(packet, now=NOW)

        self.assertEqual(state["status"], "NORMAL")
        self.assertEqual(state["sonar_cm"], 52)
        self.assertEqual(state["accel_ms2"], 12.4)

    def test_heartbeat_updates_battery_without_losing_sensor_values(self):
        previous = {
            "node_id": 2,
            "status": "NORMAL",
            "sonar_cm": 52,
            "accel_ms2": 12.4,
        }
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [78, 0],
        }

        state = build_buoy_state(packet, previous, now=NOW)

        self.assertEqual(state["battery_pct"], 78)
        self.assertEqual(state["sonar_cm"], 52)
        self.assertEqual(state["accel_ms2"], 12.4)
        self.assertFalse(state["relay_only"])

    def test_heartbeat_degraded_bit_sets_relay_only_and_latches(self):
        degraded_hb = {
            "node_id": 3,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [60, 0x01],
        }
        state = build_buoy_state(degraded_hb, previous=None, now=NOW)
        self.assertTrue(state["relay_only"])

        # heartbeat가 아닌 후속 패킷에서도 sticky하게 유지된다.
        relay_pkt = {
            "node_id": 3,
            "msg_type": "RELAY",
            "topic": TOPIC_SENSOR_RAW,
            "ttl": 2,
            "payload": [40, 100],
        }
        next_state = build_buoy_state(relay_pkt, state, now=NOW)
        self.assertTrue(next_state["relay_only"])

    def test_alert_and_clear_change_status(self):
        alert_packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_ALERT,
            "ttl": 3,
            "payload": [91],
        }
        clear_packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_ALERT_CLEAR,
            "ttl": 3,
            "payload": [],
        }

        alert_state = build_buoy_state(alert_packet, now=NOW)
        clear_state = build_buoy_state(clear_packet, alert_state, now=NOW)

        self.assertEqual(alert_state["status"], "ALERT")
        self.assertEqual(alert_state["alert_confidence"], 91)
        self.assertEqual(clear_state["status"], "NORMAL")
        self.assertEqual(clear_state["alert_confidence"], 0)


if __name__ == "__main__":
    unittest.main()
