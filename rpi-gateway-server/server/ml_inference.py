from __future__ import annotations

import logging
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from state import TOPIC_SENSOR_RAW


logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_PACKAGE_ROOT = REPO_ROOT / "detection_ml_v1"
DEFAULT_MODEL_PATH = ML_PACKAGE_ROOT / "artifacts" / "bath_all_buoys_cv_v1" / "model.joblib"

if str(ML_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_PACKAGE_ROOT))

from rescue_detection_ml.features import DetectionFeatureConfig, build_feature_table  # noqa: E402
from rescue_detection_ml.modeling import load_model_bundle, predict_feature_table  # noqa: E402


LABEL_TO_RISK = {
    "CALM": "LOW",
    "ENVIRONMENTAL_WAVE": "MEDIUM",
    "DUMMY_SPLASH": "HIGH",
}


@dataclass(frozen=True)
class MlPrediction:
    label: str
    risk: str
    confidence: int
    status: str
    window_start_ms: int
    window_end_ms: int
    baseline_window_count: int

    def to_state(self) -> dict[str, Any]:
        return {
            "ml_label": self.label,
            "ml_risk": self.risk,
            "ml_confidence": self.confidence,
            "ml_window_start_ms": self.window_start_ms,
            "ml_window_end_ms": self.window_end_ms,
            "baseline_window_count": self.baseline_window_count,
            "status": self.status,
            "alert_confidence": self.confidence if self.status in {"SUSPECT", "ALERT"} else 0,
        }


class LiveMlClassifier:
    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL_PATH,
        *,
        bundle: dict[str, Any] | None = None,
        max_samples_per_node: int = 240,
        alert_threshold: float = 0.70,
    ) -> None:
        self.model_path = Path(model_path)
        self.bundle = bundle or self._load_bundle(self.model_path)
        self.max_samples_per_node = max_samples_per_node
        self.alert_threshold = alert_threshold
        self.samples: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max_samples_per_node)
        )
        feature_config = self.bundle.get("feature_config", {})
        self.config = DetectionFeatureConfig(**feature_config) if feature_config else DetectionFeatureConfig(
            window_seconds=10.0,
            stride_seconds=5.0,
        )

    @property
    def enabled(self) -> bool:
        return self.bundle is not None

    @classmethod
    def disabled(cls) -> "LiveMlClassifier":
        instance = cls.__new__(cls)
        instance.model_path = DEFAULT_MODEL_PATH
        instance.bundle = None
        instance.max_samples_per_node = 0
        instance.alert_threshold = 0.70
        instance.samples = defaultdict(deque)
        instance.config = DetectionFeatureConfig(window_seconds=10.0, stride_seconds=5.0)
        return instance

    def add_packet(
        self,
        packet: Mapping[str, Any],
        state: Mapping[str, Any],
        now: datetime,
    ) -> MlPrediction | None:
        if not self.enabled or int(packet.get("topic", 0)) != TOPIC_SENSOR_RAW:
            return None

        node_id = int(packet["node_id"])
        sonar = state.get("sonar_cm")
        accel = state.get("accel_ms2")
        if sonar is None or accel is None:
            return None

        self.samples[node_id].append(
            {
                "timestamp_ms": int(now.timestamp() * 1000),
                "buoy_id": str(node_id),
                "sonar_cm": float(sonar),
                "accel_mag_ms2": float(accel),
                "sonar_valid": 1,
                "sonar_timeout": 0,
                "label": "",
            }
        )
        return self.predict_node(node_id)

    def predict_node(self, node_id: int) -> MlPrediction | None:
        rows = list(self.samples.get(node_id, []))
        if len(rows) < self.config.min_samples_per_window:
            return None

        raw = pd.DataFrame(rows)
        features = build_feature_table(raw, self.config)
        if features.empty:
            return None

        predictions = predict_feature_table(self.bundle, features)
        latest = predictions.iloc[-1]
        label = str(latest["predicted_label"])
        confidence = self._confidence_for_latest_window(latest)
        return MlPrediction(
            label=label,
            risk=LABEL_TO_RISK.get(label, "UNKNOWN"),
            confidence=confidence,
            status=_status_for_prediction(label, confidence, self.alert_threshold),
            window_start_ms=int(latest["window_start_ms"]),
            window_end_ms=int(latest["window_end_ms"]),
            baseline_window_count=int(latest.get("baseline_window_count", 0)),
        )

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model_path": str(self.model_path),
            "window_seconds": self.config.window_seconds,
            "stride_seconds": self.config.stride_seconds,
            "sample_counts": {str(node_id): len(rows) for node_id, rows in self.samples.items()},
        }

    def _confidence_for_latest_window(self, latest: pd.Series) -> int:
        model = self.bundle["model"]
        feature_columns = list(self.bundle["feature_columns"])
        if not hasattr(model, "predict_proba"):
            return 100

        x = pd.DataFrame([latest[feature_columns].astype(float).to_dict()])
        probabilities = model.predict_proba(x)[0]
        return int(round(float(max(probabilities)) * 100))

    @staticmethod
    def _load_bundle(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            logger.warning("ML model not found: %s", path)
            return None
        return load_model_bundle(path)


def _status_for_prediction(label: str, confidence: int, alert_threshold: float) -> str:
    if label == "DUMMY_SPLASH":
        return "ALERT" if confidence >= int(alert_threshold * 100) else "SUSPECT"
    return "NORMAL"
