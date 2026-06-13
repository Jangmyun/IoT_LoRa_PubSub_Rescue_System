import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prepare_labeled_dataset import (  # noqa: E402
    load_collection_csv,
    parse_run_spec,
    trim_by_elapsed_seconds,
)


class PrepareLabeledDatasetTests(unittest.TestCase):
    def test_parse_numeric_label_alias(self):
        path, label = parse_run_spec("csv_result_2.csv=1")

        self.assertEqual(path, Path("csv_result_2.csv"))
        self.assertEqual(label, "ENVIRONMENTAL_WAVE")

    def test_loads_prefixed_firmware_log_and_stamps_label(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "csv_result_1.log"
            path.write_text(
                "[INFO] boot\n"
                "CSV,timestamp_ms,buoy_id,sonar_cm,accel_mag_ms2,sonar_valid,sonar_timeout,label\n"
                "CSV,100,1,82.00,9.800,1,0,\n",
                encoding="utf-8",
            )

            frame = load_collection_csv(path, "CALM")

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["label"], "CALM")
        self.assertEqual(frame.iloc[0]["sonar_cm"], "82.00")

    def test_trims_start_and_end_seconds(self):
        frame = pd.DataFrame(
            {
                "timestamp_ms": ["0", "1000", "2000", "3000"],
                "buoy_id": ["1"] * 4,
                "sonar_cm": ["82"] * 4,
                "accel_mag_ms2": ["9.8"] * 4,
                "sonar_valid": ["1"] * 4,
                "sonar_timeout": ["0"] * 4,
                "label": ["CALM"] * 4,
            }
        )

        trimmed = trim_by_elapsed_seconds(frame, 1.0, 1.0)

        self.assertEqual(trimmed["timestamp_ms"].tolist(), ["1000", "2000"])


if __name__ == "__main__":
    unittest.main()
