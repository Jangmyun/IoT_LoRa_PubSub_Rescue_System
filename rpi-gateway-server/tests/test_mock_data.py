import unittest
from datetime import datetime

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from mock_data import generate_mock_packets
from state import TOPIC_ALERT, TOPIC_SENSOR_RAW


class MockDataTests(unittest.TestCase):
    def test_generate_requested_count_with_required_fields(self):
        packets = generate_mock_packets(12, seed=7, end_time=datetime(2026, 6, 10, 12, 0, 0))

        self.assertEqual(len(packets), 12)
        for packet in packets:
            self.assertIn("node_id", packet)
            self.assertIn("msg_id", packet)
            self.assertIn("topic", packet)
            self.assertIn("payload", packet)
            self.assertIn("mocked_at", packet)
            self.assertIsInstance(packet["payload"], list)

    def test_generation_is_deterministic_for_same_seed(self):
        end_time = datetime(2026, 6, 10, 12, 0, 0)

        first = generate_mock_packets(8, seed=123, end_time=end_time)
        second = generate_mock_packets(8, seed=123, end_time=end_time)

        self.assertEqual(first, second)

    def test_sensor_payload_matches_lora_packed_limits(self):
        packets = generate_mock_packets(30, seed=5, end_time=datetime(2026, 6, 10, 12, 0, 0))
        sensor_packets = [packet for packet in packets if packet["topic"] == TOPIC_SENSOR_RAW]

        self.assertGreater(len(sensor_packets), 0)
        for packet in sensor_packets:
            self.assertLessEqual(len(packet["payload"]), 2)
            for value in packet["payload"]:
                self.assertGreaterEqual(value, 0)
                self.assertLessEqual(value, 255)

    def test_recent_history_contains_an_active_alert(self):
        packets = generate_mock_packets(36, seed=9, end_time=datetime(2026, 6, 10, 12, 0, 0))

        self.assertTrue(any(packet["topic"] == TOPIC_ALERT and packet["node_id"] == 2 for packet in packets[-9:]))


if __name__ == "__main__":
    unittest.main()
