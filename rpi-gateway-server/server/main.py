import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import json

from mock_data import generate_mock_packets
from ml_inference import DEFAULT_MODEL_PATH, LiveMlClassifier
from recorder import CsvRecorder
from state import TOPIC_SENSOR_RAW, build_buoy_state, build_event, compute_relay_only

app = FastAPI(title="LoRa Rescue Gateway Server")

# --- Buoy state store ---
# key: node_id, value: buoy state dict
buoy_states: dict[int, dict] = {}
event_history: list[dict] = []
MAX_EVENT_HISTORY = 100
MOCK_DATA_ENABLED = os.getenv("MOCK_DATA", "1").lower() not in {"0", "false", "no", "off"}
RECORDING_DIR = os.getenv("RECORDING_DIR", "recordings")
ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", str(DEFAULT_MODEL_PATH))
SENSOR_RAW_TIMEOUT_S = float(os.getenv("SENSOR_RAW_TIMEOUT_S", "30"))
ML_SUSPECT_THRESHOLD = float(os.getenv("ML_SUSPECT_THRESHOLD", "0.30"))
SONAR_DISTANCE_THRESHOLD_CM = float(os.getenv("SONAR_DISTANCE_THRESHOLD_CM", "25"))
SONAR_WARNING_CONFIDENCE = int(os.getenv("SONAR_WARNING_CONFIDENCE", "100"))
recorder = CsvRecorder(RECORDING_DIR)
ml_classifier = LiveMlClassifier(ML_MODEL_PATH, suspect_threshold=ML_SUSPECT_THRESHOLD)


# --- WebSocket connection manager ---
class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self._connections -= dead


manager = ConnectionManager()


# --- Static / HTML ---
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


# --- Packet ingestion (called by gateway) ---

class LoRaPacket(BaseModel):
    node_id: int
    msg_id: int
    msg_type: str          # "PUBLISH" | "ACK" | "RELAY"
    topic: int
    ttl: int
    payload: Optional[list[int]] = None
    rssi: Optional[int] = None
    snr: Optional[float] = None


def _remember_event(event: dict) -> None:
    event_history.append(event)
    del event_history[:-MAX_EVENT_HISTORY]


def apply_sonar_distance_rule(
    packet: dict,
    state: dict,
    *,
    threshold_cm: float = SONAR_DISTANCE_THRESHOLD_CM,
    warning_confidence: int = SONAR_WARNING_CONFIDENCE,
) -> bool:
    if int(packet.get("topic", 0)) != TOPIC_SENSOR_RAW:
        return False

    previous_triggered = bool(state.get("sonar_rule_triggered"))
    sonar = state.get("sonar_cm")
    triggered = sonar is not None and float(sonar) <= threshold_cm

    state["sonar_rule_threshold_cm"] = threshold_cm
    state["sonar_rule_triggered"] = triggered
    state["sonar_rule_label"] = "NEAR_OBJECT" if triggered else ""

    if triggered:
        if state.get("status") != "ALERT":
            state["status"] = "SUSPECT"
        state["alert_confidence"] = max(
            int(state.get("alert_confidence") or 0),
            warning_confidence,
        )
    elif previous_triggered and not _ml_is_suspect(state):
        if state.get("status") == "SUSPECT":
            state["status"] = "NORMAL"
        state["alert_confidence"] = 0

    return triggered


def _ml_is_suspect(state: dict) -> bool:
    return state.get("ml_status") in {"SUSPECT", "ALERT"}


def _sensor_detection_text(packet: dict, state: dict, prediction) -> str:
    parts = [f"부표 {packet['node_id']}"]
    if prediction is not None:
        parts.append(
            f"ml={prediction.label} "
            f"victim_probability={prediction.victim_probability}% "
            f"confidence={prediction.confidence}%"
        )
    if state.get("sonar_rule_triggered"):
        parts.append(
            f"sonar<={state['sonar_rule_threshold_cm']:g}cm "
            f"current={state.get('sonar_cm')}cm"
        )
    return " ".join(parts)


def apply_packet(packet: dict, now: datetime | None = None) -> tuple[dict, dict]:
    node_id = int(packet["node_id"])
    current_time = now or datetime.now()
    state = build_buoy_state(packet, buoy_states.get(node_id), current_time, SENSOR_RAW_TIMEOUT_S)
    prediction = ml_classifier.add_packet(packet, state, current_time)
    if prediction is not None:
        state.update(prediction.to_state())
    sonar_triggered = apply_sonar_distance_rule(packet, state)
    event = build_event(packet, state, current_time)
    if (
        int(packet.get("topic", 0)) == TOPIC_SENSOR_RAW
        and (prediction is not None or sonar_triggered)
    ):
        event["level"] = state["status"]
        event["text"] = _sensor_detection_text(packet, state, prediction)
    buoy_states[node_id] = state
    _remember_event(event)
    recorder.record_packet(packet, state, current_time)
    return state, event


@app.post("/api/packet")
async def receive_packet(packet: LoRaPacket):
    state, event = apply_packet(packet.model_dump())

    await manager.broadcast({
        "type": "packet",
        "buoy": state,
        "event": event,
        "raw": packet.model_dump(),
        "recording": recorder.status(),
        "ml": ml_classifier.status(),
    })
    return {"ok": True}


# --- REST: current buoy states ---
@app.get("/api/buoys")
async def get_buoys():
    now = datetime.now()
    result = []
    for s in buoy_states.values():
        buoy = dict(s)
        buoy["relay_only"] = compute_relay_only(s, now, SENSOR_RAW_TIMEOUT_S)
        result.append(buoy)
    return result


@app.get("/api/events")
async def get_events():
    return event_history


@app.get("/api/recording")
async def get_recording_status():
    return recorder.status()


@app.get("/api/ml")
async def get_ml_status():
    return ml_classifier.status()


@app.post("/api/recording/start")
async def start_recording():
    status = recorder.start()
    await manager.broadcast({"type": "recording", "recording": status})
    return status


@app.post("/api/recording/stop")
async def stop_recording():
    status = recorder.stop()
    await manager.broadcast({"type": "recording", "recording": status})
    return status


@app.on_event("startup")
async def startup_seed_mock_data():
    if not MOCK_DATA_ENABLED or buoy_states:
        return
    for packet in generate_mock_packets():
        mocked_at = datetime.fromisoformat(packet.pop("mocked_at"))
        apply_packet(packet, mocked_at)


# --- WebSocket endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send current snapshot on connect
    await ws.send_text(json.dumps({
        "type": "init",
        "buoys": list(buoy_states.values()),
        "events": event_history,
        "recording": recorder.status(),
        "ml": ml_classifier.status(),
    }, ensure_ascii=False))
    try:
        while True:
            # Keep connection alive; gateway → REST, not WS
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
