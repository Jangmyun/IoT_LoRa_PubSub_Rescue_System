from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import json
from datetime import datetime
from typing import Optional

app = FastAPI(title="LoRa Rescue Gateway Server")

# --- Buoy state store ---
# key: node_id, value: buoy state dict
buoy_states: dict[int, dict] = {}


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

# Topic constants (mirrors LoRaPubSub.h)
_TOPIC_ALERT       = 0x10
_TOPIC_ALERT_CLEAR = 0x11


class LoRaPacket(BaseModel):
    node_id: int
    msg_id: int
    msg_type: str          # "PUBLISH" | "ACK" | "RELAY"
    topic: int
    ttl: int
    payload: Optional[list[int]] = None
    rssi: Optional[int] = None
    snr: Optional[float] = None


def _resolve_status(packet: "LoRaPacket", prev_status: str) -> str:
    if packet.topic == _TOPIC_ALERT:
        return "ALERT"
    if packet.topic == _TOPIC_ALERT_CLEAR:
        return "NORMAL"
    # HEARTBEAT / SENSOR_RAW 등 — 기존 경보 상태 유지
    return prev_status


@app.post("/api/packet")
async def receive_packet(packet: LoRaPacket):
    prev = buoy_states.get(packet.node_id, {})
    status = _resolve_status(packet, prev.get("status", "NORMAL"))

    buoy_states[packet.node_id] = {
        "node_id": packet.node_id,
        "status": status,
        "last_seen": datetime.now().isoformat(timespec="seconds"),
        "msg_type": packet.msg_type,
        "topic": packet.topic,
        "ttl": packet.ttl,
        "rssi": packet.rssi,
        "snr": packet.snr,
    }

    await manager.broadcast({
        "type": "packet",
        "buoy": buoy_states[packet.node_id],
        "raw": packet.model_dump(),
    })
    return {"ok": True}


# --- REST: current buoy states ---
@app.get("/api/buoys")
async def get_buoys():
    return list(buoy_states.values())


# --- WebSocket endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send current snapshot on connect
    await ws.send_text(json.dumps({
        "type": "init",
        "buoys": list(buoy_states.values()),
    }, ensure_ascii=False))
    try:
        while True:
            # Keep connection alive; gateway → REST, not WS
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
