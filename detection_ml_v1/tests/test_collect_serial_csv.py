import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collect_serial_csv import parse_csv_line  # noqa: E402


class CollectSerialCsvTests(unittest.TestCase):
    def test_ignores_non_csv_log_lines(self):
        self.assertIsNone(parse_csv_line("[INFO] sensors configured: 2 software objects"))

    def test_ignores_csv_header(self):
        line = "CSV,timestamp_ms,buoy_id,sonar_cm,accel_mag_ms2,sonar_valid,sonar_timeout,label"

        self.assertIsNone(parse_csv_line(line))

    def test_parses_firmware_csv_line_and_stamps_label(self):
        line = "CSV,1234,1,30.70,11.010,1,0,"

        row = parse_csv_line(line, "CALM")

        self.assertEqual(row["timestamp_ms"], "1234")
        self.assertEqual(row["buoy_id"], "1")
        self.assertEqual(row["sonar_cm"], "30.70")
        self.assertEqual(row["accel_mag_ms2"], "11.010")
        self.assertEqual(row["sonar_valid"], "1")
        self.assertEqual(row["sonar_timeout"], "0")
        self.assertEqual(row["label"], "CALM")


if __name__ == "__main__":
    unittest.main()
