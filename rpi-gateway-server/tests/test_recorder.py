import csv
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from recorder import CSV_COLUMNS, CsvRecorder  # noqa: E402
from state import TOPIC_HEARTBEAT, TOPIC_SENSOR_RAW  # noqa: E402


NOW = datetime(2026, 6, 13, 12, 0, 0)


class CsvRecorderTests(unittest.TestCase):
    def test_start_creates_incrementing_csv_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CsvRecorder(tmpdir)

            first = recorder.start()
            recorder.stop()
            second = recorder.start()
            recorder.stop()

            self.assertTrue(first["current_file"].endswith("csv_result_001.csv"))
            self.assertTrue(second["current_file"].endswith("csv_result_002.csv"))

    def test_records_only_sensor_packets_with_training_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = CsvRecorder(tmpdir)
            status = recorder.start()
            sensor_packet = {
                "node_id": 2,
                "topic": TOPIC_SENSOR_RAW,
                "payload": [82, 98],
            }
            heartbeat_packet = {
                "node_id": 2,
                "topic": TOPIC_HEARTBEAT,
                "payload": [90, 0],
            }

            self.assertTrue(
                recorder.record_packet(
                    sensor_packet,
                    {"sonar_cm": 82, "accel_ms2": 9.8},
                    NOW,
                )
            )
            self.assertFalse(
                recorder.record_packet(
                    heartbeat_packet,
                    {"battery_pct": 90},
                    NOW,
                )
            )
            recorder.stop()

            with Path(status["current_file"]).open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            self.assertEqual(reader.fieldnames, CSV_COLUMNS)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["buoy_id"], "2")
            self.assertEqual(rows[0]["sonar_cm"], "82")
            self.assertEqual(rows[0]["accel_mag_ms2"], "9.8")
            self.assertEqual(rows[0]["label"], "")


if __name__ == "__main__":
    unittest.main()
