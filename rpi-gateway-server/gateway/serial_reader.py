"""
Serial reader for the LoRa-to-USB bridge connected at /dev/ttyACM0.

프레이밍 전략:
  1. 0xAB(preamble) 를 만날 때까지 1바이트씩 스캔
  2. 다음 바이트(msg_type) 로 패킷 종류 결정
  3. 해당 패킷 크기만큼 나머지 바이트 읽기
  4. CRC 검증 → 실패 시 폐기, 재스캔
  5. 패킷 직후 RSSI/SNR 메타 3바이트 읽기

RSSI/SNR 시리얼 포맷 (패킷 바이트 바로 뒤, 펌웨어가 추가로 송신):
  [rssi: int16 LE (2B)]  LoRa.packetRssi()  단위: dBm
  [snr_x4: int8  (1B)]   (int8_t)(LoRa.packetSnr() * 4)  0.25dB 해상도

펌웨어 측 송신 예 (Arduino):
  int16_t rssi   = (int16_t)LoRa.packetRssi();
  int8_t  snr_x4 = (int8_t)(LoRa.packetSnr() * 4.0f);
  Serial.write(packet_buf, packet_size);
  Serial.write((uint8_t*)&rssi,   2);
  Serial.write((uint8_t*)&snr_x4, 1);

직렬 읽기는 스레드에서 블로킹으로 수행하고,
패킷이 완성되면 asyncio.run_coroutine_threadsafe 로 on_packet 콜백 호출.
연결이 끊기면 RECONNECT_DELAY 초 후 자동 재시도.
"""

import asyncio
import logging
import struct
from typing import Awaitable, Callable

import serial

from lib.packet import (
    LP_PREAMBLE,
    LoRaAck,
    LoRaHeader,
    LoRaPublish,
    MsgType,
)

# RSSI(int16 LE) + snr_x4(int8) = 3바이트
_META_FMT  = "<hb"
_META_SIZE = struct.calcsize(_META_FMT)  # 3

logger = logging.getLogger(__name__)

SERIAL_PORT     = "/dev/ttyACM0"
BAUD_RATE       = 115200
RECONNECT_DELAY = 3.0   # seconds

PacketCallback = Callable[[LoRaPublish | LoRaAck], Awaitable[None]]


# ── Public entry point ─────────────────────────────────────────────

async def serial_read_loop(
    on_packet: PacketCallback,
    port: str = SERIAL_PORT,
    baud: int  = BAUD_RATE,
) -> None:
    """영구 루프: 시리얼 열기 → 패킷 수신 → on_packet 호출 → 오류 시 재연결."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(
                None, _blocking_loop, port, baud, on_packet, loop
            )
        except Exception as exc:
            logger.error("serial error: %s — retry in %.1fs", exc, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)


# ── Blocking thread ────────────────────────────────────────────────

def _blocking_loop(
    port: str,
    baud: int,
    on_packet: PacketCallback,
    loop: asyncio.AbstractEventLoop,
) -> None:
    with serial.Serial(port, baud, timeout=1) as ser:
        logger.info("serial opened: %s @ %d baud", port, baud)
        while True:
            pkt = _read_one_packet(ser)
            if pkt is not None:
                asyncio.run_coroutine_threadsafe(on_packet(pkt), loop)


def _read_one_packet(ser: serial.Serial) -> LoRaPublish | LoRaAck | None:
    """
    블로킹: preamble 을 찾아 패킷 1개를 완전히 읽어 반환.
    타임아웃·프레이밍 오류·CRC 실패 시 None 반환.
    """
    # 1. preamble 스캔
    b = ser.read(1)
    if not b or b[0] != LP_PREAMBLE:
        return None

    # 2. 나머지 헤더 4바이트 (msg_type | node_id | msg_id | ttl)
    rest = ser.read(LoRaHeader.SIZE - 1)
    if len(rest) < LoRaHeader.SIZE - 1:
        logger.debug("header read timeout")
        return None

    msg_type = rest[0]
    buf = bytes([LP_PREAMBLE]) + rest

    # 3. 패킷 종류별 바디 읽기
    if msg_type in (MsgType.PUBLISH, MsgType.RELAY):
        return _read_publish(ser, buf)

    if msg_type == MsgType.ACK:
        return _read_ack(ser, buf)

    logger.debug("unknown msg_type=0x%02x — skipping", msg_type)
    return None


def _read_meta(ser: serial.Serial) -> tuple[int | None, float | None]:
    """패킷 직후 3바이트에서 RSSI/SNR 읽기. 타임아웃 시 (None, None) 반환."""
    raw = ser.read(_META_SIZE)
    if len(raw) < _META_SIZE:
        logger.debug("meta (rssi/snr) read timeout")
        return None, None
    rssi, snr_x4 = struct.unpack(_META_FMT, raw)
    return rssi, snr_x4 / 4.0


def _read_publish(ser: serial.Serial, buf: bytes) -> LoRaPublish | None:
    need = LoRaPublish.SIZE - LoRaHeader.SIZE
    body = ser.read(need)
    if len(body) < need:
        logger.debug("publish body timeout")
        return None
    buf += body
    try:
        pkt = LoRaPublish.unpack(buf)
    except ValueError as exc:
        logger.warning("publish unpack error: %s  raw=%s", exc, buf.hex())
        return None
    if not pkt.verify_crc():
        logger.warning("publish CRC mismatch raw=%s", buf.hex())
        return None
    pkt.rssi, pkt.snr = _read_meta(ser)
    logger.info(
        "RX PUBLISH  node=%d msg=%d topic=0x%02x payload=%s ttl=%d rssi=%s snr=%s",
        pkt.header.node_id, pkt.header.msg_id,
        pkt.topic, pkt.valid_payload.hex(),
        pkt.header.ttl, pkt.rssi, pkt.snr,
    )
    return pkt


def _read_ack(ser: serial.Serial, buf: bytes) -> LoRaAck | None:
    need = LoRaAck.SIZE - LoRaHeader.SIZE
    body = ser.read(need)
    if len(body) < need:
        logger.debug("ack body timeout")
        return None
    buf += body
    try:
        pkt = LoRaAck.unpack(buf)
    except ValueError as exc:
        logger.warning("ack unpack error: %s  raw=%s", exc, buf.hex())
        return None
    if not pkt.verify_crc():
        logger.warning("ack CRC mismatch raw=%s", buf.hex())
        return None
    pkt.rssi, pkt.snr = _read_meta(ser)
    logger.info(
        "RX ACK  node=%d ack_for=%d rssi=%s snr=%s",
        pkt.header.node_id, pkt.ack_msg_id, pkt.rssi, pkt.snr,
    )
    return pkt
