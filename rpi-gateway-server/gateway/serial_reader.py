"""
Serial reader for the LoRa-to-USB bridge connected at /dev/ttyACM0.

프레이밍 전략:
  1. 0xAB(preamble) 를 만날 때까지 1바이트씩 스캔
  2. 다음 바이트(msg_type) 로 패킷 종류 결정
  3. 해당 패킷 크기만큼 나머지 바이트 읽기
  4. CRC 검증 → 실패 시 폐기, 재스캔
  5. 패킷 직후 3바이트(RSSI int16 LE + SNR int8) 를 항상 소비

직렬 읽기는 스레드에서 블로킹으로 수행하고,
패킷이 완성되면 asyncio.run_coroutine_threadsafe 로 on_packet 콜백 호출.
연결이 끊기면 RECONNECT_DELAY 초 후 자동 재시도.
"""

import asyncio
import logging
import struct
import threading
from typing import Awaitable, Callable

import serial

from lib.packet import (
    LP_PREAMBLE,
    LoRaAck,
    LoRaHeader,
    LoRaPublish,
    MsgType,
)

logger = logging.getLogger(__name__)

SERIAL_PORT     = "/dev/ttyACM0"
BAUD_RATE       = 115200
RECONNECT_DELAY = 3.0   # seconds

# gateway_main.cpp 가 LoRaPublish 직후에 붙이는 메타데이터 포맷
_META_FMT  = "<hb"                    # int16 LE (rssi) + int8 (snr*4)
_META_SIZE = struct.calcsize(_META_FMT)  # 3 bytes

PacketCallback = Callable[[LoRaPublish | LoRaAck], Awaitable[None]]

# ASCII 라인 누적 버퍼 (펌웨어 텍스트 출력 감지용)
_ascii_buf: list[int] = []

def _log_ascii_byte(byte: int) -> None:
    """수신 바이트가 ASCII 텍스트일 때 라인 단위로 DEBUG 로그 출력."""
    if byte in (0x0A, 0x0D):
        if _ascii_buf:
            line = bytes(_ascii_buf).decode("ascii", errors="replace").strip()
            if line:
                logger.debug("[serial ASCII] %s", line)
            _ascii_buf.clear()
    else:
        _ascii_buf.append(byte)


# ── Public entry point ─────────────────────────────────────────────

async def serial_read_loop(
    on_packet: PacketCallback,
    port: str = SERIAL_PORT,
    baud: int  = BAUD_RATE,
) -> None:
    """영구 루프: 시리얼 열기 → 패킷 수신 → on_packet 호출 → 오류 시 재연결."""
    loop = asyncio.get_running_loop()
    stop_flag = threading.Event()
    while True:
        try:
            await loop.run_in_executor(
                None, _blocking_loop, port, baud, on_packet, loop, stop_flag
            )
        except asyncio.CancelledError:
            stop_flag.set()   # 블로킹 스레드에 종료 신호
            raise
        except Exception as exc:
            logger.error("serial error: %s — retry in %.1fs", exc, RECONNECT_DELAY)
            await asyncio.sleep(RECONNECT_DELAY)


# ── Blocking thread ────────────────────────────────────────────────

def _blocking_loop(
    port: str,
    baud: int,
    on_packet: PacketCallback,
    loop: asyncio.AbstractEventLoop,
    stop_flag: threading.Event,
) -> None:
    with serial.Serial(port, baud, timeout=1) as ser:
        logger.info("serial opened: %s @ %d baud", port, baud)
        while not stop_flag.is_set():
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
    if not b:
        return None
    if b[0] != LP_PREAMBLE:
        # ASCII 가시 문자면 텍스트 라인으로 누적해서 출력 (펌웨어 디버그 출력 감지용)
        if 0x20 <= b[0] <= 0x7E or b[0] in (0x0A, 0x0D):
            _log_ascii_byte(b[0])
        else:
            logger.debug("non-preamble byte: 0x%02x", b[0])
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


def _read_publish(ser: serial.Serial, buf: bytes) -> LoRaPublish | None:
    need = LoRaPublish.SIZE - LoRaHeader.SIZE
    body = ser.read(need)
    if len(body) < need:
        logger.debug("publish body timeout")
        return None
    buf += body

    # gateway_main.cpp 가 LoRaPublish 직후에 RSSI/SNR 3바이트를 전송한다.
    # 검증 결과와 무관하게 항상 소비해야 다음 패킷 정렬이 유지된다.
    meta = ser.read(_META_SIZE)

    try:
        pkt = LoRaPublish.unpack(buf)
    except ValueError as exc:
        logger.warning("publish unpack error: %s  raw=%s", exc, buf.hex())
        return None
    if not pkt.verify_crc():
        logger.warning("publish CRC mismatch raw=%s", buf.hex())
        return None

    if len(meta) == _META_SIZE:
        rssi, snr_x4 = struct.unpack(_META_FMT, meta)
        pkt.rssi = rssi
        pkt.snr  = snr_x4 / 4.0

    logger.info(
        "RX PUBLISH  node=%d msg=%d topic=0x%02x payload=%s rssi=%s ttl=%d",
        pkt.header.node_id, pkt.header.msg_id,
        pkt.topic, pkt.valid_payload.hex(),
        pkt.rssi, pkt.header.ttl,
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
    logger.info(
        "RX ACK  node=%d ack_for=%d",
        pkt.header.node_id, pkt.ack_msg_id,
    )
    return pkt
