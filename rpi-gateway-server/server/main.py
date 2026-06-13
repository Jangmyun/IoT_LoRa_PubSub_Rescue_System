import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import json

from mock_data import generate_mock_packets
from recorder import CsvRecorder
from state import build_buoy_state, build_event

app = FastAPI(title="LoRa Rescue Gateway Server")

# --- Buoy state store ---
# key: node_id, value: buoy state dict
buoy_states: dict[int, dict] = {}
event_history: list[dict] = []
MAX_EVENT_HISTORY = 100
MOCK_DATA_ENABLED = os.getenv("MOCK_DATA", "1").lower() not in {"0", "false", "no", "off"}
RECORDING_DIR = os.getenv("RECORDING_DIR", "recordings")
recorder = CsvRecorder(RECORDING_DIR)


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


def apply_packet(packet: dict, now: datetime | None = None) -> tuple[dict, dict]:
    node_id = int(packet["node_id"])
    current_time = now or datetime.now()
    state = build_buoy_state(packet, buoy_states.get(node_id), current_time)
    event = build_event(packet, state, current_time)
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
    })
    return {"ok": True}


# --- REST: current buoy states ---
@app.get("/api/buoys")
async def get_buoys():
    return list(buoy_states.values())


@app.get("/api/events")
async def get_events():
    return event_history


@app.get("/api/recording")
async def get_recording_status():
    return recorder.status()


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
    }, ensure_ascii=False))
    try:
        while True:
            # Keep connection alive; gateway → REST, not WS
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
