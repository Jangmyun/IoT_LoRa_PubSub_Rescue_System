import unittest
from datetime import datetime, timedelta

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
    compute_relay_only,
)


NOW = datetime(2026, 6, 10, 12, 0, 0)
TIMEOUT_S = 30.0


class ComputeRelayOnlyTests(unittest.TestCase):
    def test_true_when_no_sensor_raw_ever(self):
        self.assertTrue(compute_relay_only({}, NOW, TIMEOUT_S))

    def test_false_when_sensor_raw_just_received(self):
        state = {"last_sensor_raw_at": NOW.isoformat(timespec="seconds")}
        self.assertFalse(compute_relay_only(state, NOW, TIMEOUT_S))

    def test_false_when_sensor_raw_within_timeout(self):
        last = (NOW - timedelta(seconds=20)).isoformat(timespec="seconds")
        state = {"last_sensor_raw_at": last}
        self.assertFalse(compute_relay_only(state, NOW, TIMEOUT_S))

    def test_true_when_sensor_raw_stale(self):
        last = (NOW - timedelta(seconds=31)).isoformat(timespec="seconds")
        state = {"last_sensor_raw_at": last}
        self.assertTrue(compute_relay_only(state, NOW, TIMEOUT_S))


class StateTests(unittest.TestCase):
    def test_sensor_raw_decodes_packed_values(self):
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_SENSOR_RAW,
            "ttl": 3,
            "payload": [52, 124],
        }

        state = build_buoy_state(packet, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)

        self.assertEqual(state["status"], "NORMAL")
        self.assertEqual(state["sonar_cm"], 52)
        self.assertEqual(state["accel_ms2"], 12.4)

    def test_sensor_raw_sets_relay_only_false(self):
        """SENSOR_RAW 수신 시각이 기록되고 relay_only=False"""
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_SENSOR_RAW,
            "ttl": 3,
            "payload": [52, 124],
        }
        state = build_buoy_state(packet, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)

        self.assertEqual(state["last_sensor_raw_at"], NOW.isoformat(timespec="seconds"))
        self.assertFalse(state["relay_only"])

    def test_relay_only_true_when_no_sensor_raw_received(self):
        """한 번도 SENSOR_RAW를 받지 못한 노드 → relay_only=True"""
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [80, 0],
        }
        state = build_buoy_state(packet, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)
        self.assertTrue(state["relay_only"])

    def test_relay_only_false_when_sensor_raw_recent(self):
        """최근 SENSOR_RAW가 있으면 heartbeat 수신 후에도 relay_only=False"""
        previous = {
            "last_sensor_raw_at": (NOW - timedelta(seconds=10)).isoformat(timespec="seconds"),
        }
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [80, 0],
        }
        state = build_buoy_state(packet, previous, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)
        self.assertFalse(state["relay_only"])

    def test_relay_only_true_when_sensor_raw_stale(self):
        """마지막 SENSOR_RAW가 timeout 초과 → relay_only=True"""
        previous = {
            "last_sensor_raw_at": (NOW - timedelta(seconds=60)).isoformat(timespec="seconds"),
        }
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [80, 0],
        }
        state = build_buoy_state(packet, previous, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)
        self.assertTrue(state["relay_only"])

    def test_heartbeat_updates_battery_without_losing_sensor_values(self):
        previous = {
            "node_id": 2,
            "status": "NORMAL",
            "sonar_cm": 52,
            "accel_ms2": 12.4,
            "last_sensor_raw_at": NOW.isoformat(timespec="seconds"),
        }
        packet = {
            "node_id": 2,
            "msg_type": "PUBLISH",
            "topic": TOPIC_HEARTBEAT,
            "ttl": 3,
            "payload": [78, 0],
        }

        state = build_buoy_state(packet, previous, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)

        self.assertEqual(state["battery_pct"], 78)
        self.assertEqual(state["sonar_cm"], 52)
        self.assertEqual(state["accel_ms2"], 12.4)
        self.assertFalse(state["relay_only"])

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

        alert_state = build_buoy_state(alert_packet, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)
        clear_state = build_buoy_state(clear_packet, alert_state, now=NOW, sensor_raw_timeout_s=TIMEOUT_S)

        self.assertEqual(alert_state["status"], "ALERT")
        self.assertEqual(alert_state["alert_confidence"], 91)
        self.assertEqual(clear_state["status"], "NORMAL")
        self.assertEqual(clear_state["alert_confidence"], 0)


if __name__ == "__main__":
    unittest.main()
