from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, TextIO

from state import TOPIC_SENSOR_RAW


CSV_COLUMNS = [
    "timestamp_ms",
    "buoy_id",
    "sonar_cm",
    "accel_mag_ms2",
    "sonar_valid",
    "sonar_timeout",
    "label",
]


class CsvRecorder:
    def __init__(self, directory: str | Path = "recordings", prefix: str = "csv_result") -> None:
        self.directory = Path(directory)
        self.prefix = prefix
        self.active = False
        self.current_path: Path | None = None
        self.rows_written = 0
        self._handle: TextIO | None = None
        self._writer: csv.DictWriter | None = None

    def status(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "current_file": str(self.current_path) if self.current_path else None,
            "rows_written": self.rows_written,
            "next_file": str(self._next_path()),
        }

    def start(self) -> dict[str, Any]:
        if self.active:
            return self.status()

        self.directory.mkdir(parents=True, exist_ok=True)
        self.current_path = self._next_path()
        self.rows_written = 0
        self._handle = self.current_path.open("w", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=CSV_COLUMNS)
        self._writer.writeheader()
        self._handle.flush()
        self.active = True
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self._handle:
            self._handle.flush()
            self._handle.close()
        self._handle = None
        self._writer = None
        self.active = False
        return self.status()

    def record_packet(
        self,
        packet: Mapping[str, Any],
        state: Mapping[str, Any],
        now: datetime,
    ) -> bool:
        if not self.active or self._writer is None or self._handle is None:
            return False
        if int(packet.get("topic", 0)) != TOPIC_SENSOR_RAW:
            return False

        sonar = state.get("sonar_cm")
        accel = state.get("accel_ms2")
        if sonar is None or accel is None:
            return False

        self._writer.writerow(
            {
                "timestamp_ms": int(now.timestamp() * 1000),
                "buoy_id": int(packet["node_id"]),
                "sonar_cm": sonar,
                "accel_mag_ms2": accel,
                "sonar_valid": 1,
                "sonar_timeout": 0,
                "label": "",
            }
        )
        self._handle.flush()
        self.rows_written += 1
        return True

    def _next_path(self) -> Path:
        index = 1
        while True:
            path = self.directory / f"{self.prefix}_{index:03d}.csv"
            if not path.exists() and path != self.current_path:
                return path
            index += 1

    def __del__(self) -> None:
        self.stop()
