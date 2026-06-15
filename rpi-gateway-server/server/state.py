from datetime import datetime
from typing import Any, Mapping


TOPIC_ALERT = 0x10
TOPIC_ALERT_CLEAR = 0x11
TOPIC_HEARTBEAT = 0x20
TOPIC_SENSOR_RAW = 0x21

# Heartbeat status 바이트 비트 정의 (펌웨어 main.cpp와 동기화)
HB_STATUS_DEGRADED = 0x01


def _payload(packet: Mapping[str, Any]) -> list[int]:
    value = packet.get("payload") or []
    return [int(item) for item in value]


def _topic(packet: Mapping[str, Any]) -> int:
    return int(packet.get("topic", 0))


def resolve_status(packet: Mapping[str, Any], previous_status: str = "NORMAL") -> str:
    topic = _topic(packet)
    if topic == TOPIC_ALERT:
        return "ALERT"
    if topic == TOPIC_ALERT_CLEAR:
        return "NORMAL"
    return previous_status


def decode_payload(packet: Mapping[str, Any]) -> dict[str, Any]:
    topic = _topic(packet)
    payload = _payload(packet)

    if topic == TOPIC_SENSOR_RAW:
        decoded: dict[str, Any] = {}
        if len(payload) >= 1:
            decoded["sonar_cm"] = payload[0]
        if len(payload) >= 2:
            decoded["accel_ms2"] = round(payload[1] / 10.0, 1)
        return decoded

    if topic == TOPIC_HEARTBEAT:
        decoded = {}
        if len(payload) >= 1:
            decoded["battery_pct"] = payload[0]
        if len(payload) >= 2:
            decoded["device_status"] = payload[1]
            decoded["relay_only"] = bool(payload[1] & HB_STATUS_DEGRADED)
        return decoded

    if topic == TOPIC_ALERT:
        return {"alert_confidence": payload[0] if payload else 100}

    if topic == TOPIC_ALERT_CLEAR:
        return {"alert_confidence": 0}

    return {}


def build_buoy_state(
    packet: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    now = now or datetime.now()
    status = resolve_status(packet, str(previous.get("status", "NORMAL")))

    state = dict(previous)
    state.update(
        {
            "node_id": int(packet["node_id"]),
            "status": status,
            "last_seen": now.isoformat(timespec="seconds"),
            "msg_type": str(packet.get("msg_type", "PUBLISH")),
            "topic": _topic(packet),
            "ttl": int(packet.get("ttl", 0)),
            "payload": _payload(packet),
            "rssi": packet.get("rssi"),
            "snr": packet.get("snr"),
        }
    )
    decoded = decode_payload(packet)
    # relay_only는 한 번 True가 되면 sticky (펌웨어도 latch).
    previous_relay_only = bool(previous.get("relay_only"))
    state.update(decoded)
    state["relay_only"] = previous_relay_only or bool(decoded.get("relay_only", False))
    return state


def build_event(
    packet: Mapping[str, Any],
    state: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    topic = _topic(packet)
    payload = _payload(packet)

    event = {
        "timestamp": now.isoformat(timespec="seconds"),
        "level": state.get("status", "NORMAL"),
        "node_id": int(packet["node_id"]),
        "msg_type": str(packet.get("msg_type", "PUBLISH")),
        "topic": topic,
        "payload": payload,
        "rssi": packet.get("rssi"),
        "snr": packet.get("snr"),
    }

    if topic == TOPIC_SENSOR_RAW:
        sonar = state.get("sonar_cm")
        accel = state.get("accel_ms2")
        event["text"] = f"부표 {packet['node_id']} sensor sonar={sonar}cm accel={accel}m/s2"
    elif topic == TOPIC_HEARTBEAT:
        degraded_suffix = " (relay-only)" if state.get("relay_only") else ""
        event["text"] = (
            f"부표 {packet['node_id']} heartbeat battery={state.get('battery_pct')}%"
            f"{degraded_suffix}"
        )
    elif topic == TOPIC_ALERT:
        event["text"] = f"부표 {packet['node_id']} alert confidence={state.get('alert_confidence')}%"
    elif topic == TOPIC_ALERT_CLEAR:
        event["text"] = f"부표 {packet['node_id']} alert cleared"
    else:
        event["text"] = f"부표 {packet['node_id']} topic=0x{topic:02x}"

    return event
