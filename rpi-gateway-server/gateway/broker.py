"""
In-process pub/sub dispatcher.

subscribe(topic, cb)  — async 콜백 등록
  - 정확히 일치: sub_topic == pkt.topic
  - 카테고리 와일드카드: sub_topic 하위 니블이 0x0 이면 상위 니블만 비교
    예) subscribe(0x10) → 0x10, 0x11 모두 수신  (firmware 동작 동일)

dispatch(pkt)  — serial_reader 가 패킷 수신마다 호출
  ACK 패킷은 앱 레벨 구독자에게 전달하지 않는다.
"""

import asyncio
import logging
from typing import Awaitable, Callable

from lib.packet import LoRaAck, LoRaPublish

logger = logging.getLogger(__name__)

Callback = Callable[[LoRaPublish], Awaitable[None]]


_SEEN_MAX = 512  # 노드당 msg_id가 0~255 순환이므로 넉넉히 설정


class Broker:
    def __init__(self) -> None:
        # topic=None は catch-all (모든 LoRaPublish 수신)
        self._subs: list[tuple[int | None, Callback]] = []
        # (node_id, msg_id) 중복 억제 — 직접 수신 + 릴레이 수신이 동시에 도달할 때 방지
        self._seen: dict[tuple[int, int], None] = {}

    def subscribe(self, topic: int, callback: Callback) -> None:
        self._subs.append((topic, callback))
        logger.debug("subscribed topic=0x%02x", topic)

    def subscribe_all(self, callback: Callback) -> None:
        """토픽에 관계없이 모든 LoRaPublish 패킷을 수신한다."""
        self._subs.append((None, callback))
        logger.debug("subscribed all topics")

    async def dispatch(self, pkt: LoRaPublish | LoRaAck) -> None:
        if not isinstance(pkt, LoRaPublish):
            return
        key = (pkt.header.node_id, pkt.header.msg_id)
        if key in self._seen:
            logger.debug("duplicate suppressed node=%d msg=%d", *key)
            return
        self._seen[key] = None
        if len(self._seen) > _SEEN_MAX:
            del self._seen[next(iter(self._seen))]
        for sub_topic, cb in self._subs:
            if self._matches(sub_topic, pkt.topic):
                try:
                    await cb(pkt)
                except Exception:
                    logger.exception(
                        "subscriber error topic=0x%02x node=%d",
                        pkt.topic, pkt.header.node_id,
                    )

    @staticmethod
    def _matches(sub_topic: int | None, pkt_topic: int) -> bool:
        if sub_topic is None:
            return True
        if sub_topic == pkt_topic:
            return True
        # 하위 니블이 0x0 → 카테고리(상위 니블) 전체 수신
        if (sub_topic & 0x0F) == 0x00 and (sub_topic >> 4) == (pkt_topic >> 4):
            return True
        return False
