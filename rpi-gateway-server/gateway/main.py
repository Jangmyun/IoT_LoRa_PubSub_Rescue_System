"""
Gateway entry point.

흐름:
  serial_reader  →  broker.dispatch  →  forward()  →  POST /api/packet
                                                        (server → WebSocket → dashboard)

환경 변수로 설정 가능:
  SERIAL_PORT   (기본: /dev/ttyACM0)
  BAUD_RATE     (기본: 115200)
  SERVER_URL    (기본: http://localhost:8000)
  LOG_LEVEL     (기본: INFO)
"""

import asyncio
import contextlib
import logging
import os
import signal

import httpx

from broker import Broker
from lib.packet import MsgType, LoRaPublish
from serial_reader import BAUD_RATE, SERIAL_PORT, serial_read_loop

# ── 설정 ──────────────────────────────────────────────────────────
SERVER_URL  = os.getenv("SERVER_URL",  "http://localhost:8000")
SERIAL_PORT = os.getenv("SERIAL_PORT", SERIAL_PORT)
BAUD_RATE   = int(os.getenv("BAUD_RATE", str(BAUD_RATE)))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)-5s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── 핵심 로직 ─────────────────────────────────────────────────────

async def run() -> None:
    broker = Broker()
    client = httpx.AsyncClient(base_url=SERVER_URL, timeout=5.0)

    async def forward(pkt: LoRaPublish) -> None:
        body = {
            "node_id":  pkt.header.node_id,
            "msg_id":   pkt.header.msg_id,
            "msg_type": MsgType(pkt.header.msg_type).name,
            "topic":    pkt.topic,
            "ttl":      pkt.header.ttl,
            "payload":  list(pkt.valid_payload),
        }
        try:
            r = await client.post("/api/packet", json=body)
            r.raise_for_status()
            logger.debug(
                "forwarded node=%d topic=0x%02x → HTTP %d",
                pkt.header.node_id, pkt.topic, r.status_code,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning("server rejected packet: %s", exc)
        except httpx.HTTPError as exc:
            logger.warning("forward failed: %s", exc)
        except RuntimeError:
            pass  # client closed during shutdown

    broker.subscribe_all(forward)

    # Graceful shutdown on SIGINT / SIGTERM
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    reader = asyncio.create_task(
        serial_read_loop(broker.dispatch, port=SERIAL_PORT, baud=BAUD_RATE)
    )
    logger.info("gateway started  serial=%s  server=%s", SERIAL_PORT, SERVER_URL)

    await stop.wait()

    logger.info("shutting down…")
    reader.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reader
    await client.aclose()
    logger.info("gateway stopped")


# ── 진입점 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run())
