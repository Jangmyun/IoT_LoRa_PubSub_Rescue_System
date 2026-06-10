from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Iterable

from state import TOPIC_ALERT, TOPIC_ALERT_CLEAR, TOPIC_HEARTBEAT, TOPIC_SENSOR_RAW


DEFAULT_NODE_IDS = (1, 2, 3)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _sensor_payload(rng: random.Random, alert: bool) -> list[int]:
    sonar = rng.randint(18, 80) if alert else rng.randint(70, 220)
    accel = rng.uniform(12.0, 22.0) if alert else rng.uniform(9.2, 10.8)
    return [_clamp(sonar, 0, 255), _clamp(round(accel * 10), 0, 255)]


def _heartbeat_payload(rng: random.Random, index: int) -> list[int]:
    battery = _clamp(84 - index // 8 + rng.randint(-1, 1), 35, 100)
    return [battery, 0]


def generate_mock_packets(
    count: int = 36,
    *,
    seed: int | None = 20260610,
    node_ids: Iterable[int] = DEFAULT_NODE_IDS,
    interval_seconds: int = 3,
    end_time: datetime | None = None,
) -> list[dict]:
    if count <= 0:
        return []

    rng = random.Random(seed)
    nodes = list(node_ids)
    if not nodes:
        raise ValueError("node_ids must not be empty")

    end_time = end_time or datetime.now()
    start_time = end_time - timedelta(seconds=interval_seconds * (count - 1))
    alert_start = max(0, count - 9)
    previous_alert_start = max(0, count // 2 - 2)
    previous_alert_clear = min(count - 1, previous_alert_start + 3)

    packets: list[dict] = []
    msg_id = 0

    for index in range(count):
        node_id = nodes[index % len(nodes)]
        timestamp = start_time + timedelta(seconds=interval_seconds * index)
        is_active_alert = index >= alert_start and node_id == 2
        is_previous_alert = index == previous_alert_start and node_id == 1
        is_previous_clear = index == previous_alert_clear and node_id == 1

        if is_active_alert or is_previous_alert:
            topic = TOPIC_ALERT
            payload = [rng.randint(78, 96)]
        elif is_previous_clear:
            topic = TOPIC_ALERT_CLEAR
            payload = []
        elif index % 5 == 0:
            topic = TOPIC_HEARTBEAT
            payload = _heartbeat_payload(rng, index)
        else:
            topic = TOPIC_SENSOR_RAW
            payload = _sensor_payload(rng, is_active_alert)

        packets.append(
            {
                "node_id": node_id,
                "msg_id": msg_id % 256,
                "msg_type": "PUBLISH",
                "topic": topic,
                "ttl": rng.randint(1, 3),
                "payload": payload,
                "rssi": rng.randint(-118, -54),
                "snr": round(rng.uniform(-7.5, 12.0), 1),
                "mocked_at": timestamp.isoformat(timespec="seconds"),
            }
        )
        msg_id += 1

    return packets
