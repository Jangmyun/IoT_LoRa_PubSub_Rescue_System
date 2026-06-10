"""
LoRa PubSub packet definitions — mirrors LoRaPubSub.h exactly.

Packet layout (#pragma pack(1), all uint8_t):
  LoRaHeader   : preamble | msg_type | node_id | msg_id | ttl          (5 B)
  LoRaPublish  : header   | topic    | pld_len | payload[3] | crc8     (11 B)
  LoRaAck      : header   | ack_msg_id | crc8                           (7 B)

CRC-8 scope:
  LoRaPublish : header(5) + topic(1) + pld_len(1) + payload(3) = 10 bytes
  LoRaAck     : header(5) + ack_msg_id(1)                       =  6 bytes
"""

import struct
from dataclasses import dataclass, field
from enum import IntEnum

# ── Protocol constants ─────────────────────────────────────────────
LP_PREAMBLE    = 0xAB
LP_MAX_TTL     = 3
LP_MAX_RETRIES = 3
LP_MAX_PAYLOAD = 3
LP_SEEN_BUF    = 16


# ── MSG_TYPE ───────────────────────────────────────────────────────
class MsgType(IntEnum):
    PUBLISH   = 0x01
    SUBSCRIBE = 0x02
    ACK       = 0x03
    RELAY     = 0x04


# ── TOPIC (upper nibble = category) ───────────────────────────────
class Topic(IntEnum):
    ALERT       = 0x10  # payload: confidence(1B)
    ALERT_CLEAR = 0x11  # payload: —
    HEARTBEAT   = 0x20  # payload: battery(1B), status(1B)
    SENSOR_RAW  = 0x21  # payload: sonar(1B), accel(1B)
    CMD_RESET   = 0x30  # payload: —
    CMD_CONFIG  = 0x31  # payload: interval(1B), threshold(1B)


# ── NODE_ID ────────────────────────────────────────────────────────
class NodeId(IntEnum):
    PI     = 0x00
    BUOY_A = 0x01
    BUOY_B = 0x02
    BUOY_C = 0x03


# ── CRC-8 (poly=0x07, init=0x00) — matches common Arduino CRC8 ────
def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) if (crc & 0x80) else (crc << 1)
            crc &= 0xFF
    return crc


# ── LoRaHeader  5 bytes ────────────────────────────────────────────
@dataclass
class LoRaHeader:
    preamble: int = LP_PREAMBLE
    msg_type: int = 0
    node_id:  int = 0
    msg_id:   int = 0
    ttl:      int = LP_MAX_TTL

    _FMT = "<BBBBB"
    SIZE: int = struct.calcsize(_FMT)  # 5

    def pack(self) -> bytes:
        return struct.pack(
            self._FMT,
            self.preamble, self.msg_type, self.node_id, self.msg_id, self.ttl,
        )

    @classmethod
    def unpack_from(cls, buf: bytes, offset: int = 0) -> "LoRaHeader":
        return cls(*struct.unpack_from(cls._FMT, buf, offset))


# ── LoRaPublish  11 bytes ──────────────────────────────────────────
@dataclass
class LoRaPublish:
    header:   LoRaHeader
    topic:    int
    pld_len:  int
    payload:  bytes    # exactly LP_MAX_PAYLOAD (3) bytes, zero-padded
    crc8_val: int
    # ── 수신 메타데이터 (wire format 외부, serial_reader 가 채움) ──
    rssi: int | None   = field(default=None, compare=False)
    snr:  float | None = field(default=None, compare=False)

    _FMT = "<BBBBBBBBBBB"
    SIZE: int = struct.calcsize(_FMT)  # 11

    @classmethod
    def build(cls, node_id: int, msg_id: int, topic: int, payload: bytes,
              ttl: int = LP_MAX_TTL, msg_type: int = MsgType.PUBLISH) -> "LoRaPublish":
        if len(payload) > LP_MAX_PAYLOAD:
            raise ValueError(f"payload too long: {len(payload)} > {LP_MAX_PAYLOAD}")
        pld_len = len(payload)
        padded  = (payload + bytes(LP_MAX_PAYLOAD))[:LP_MAX_PAYLOAD]
        header  = LoRaHeader(LP_PREAMBLE, int(msg_type), node_id, msg_id, ttl)
        checksum = crc8(header.pack() + bytes([topic, pld_len]) + padded)
        return cls(header, topic, pld_len, padded, checksum)

    def pack(self) -> bytes:
        h = self.header
        p = (self.payload + bytes(LP_MAX_PAYLOAD))[:LP_MAX_PAYLOAD]
        return struct.pack(
            self._FMT,
            h.preamble, h.msg_type, h.node_id, h.msg_id, h.ttl,
            self.topic, self.pld_len,
            p[0], p[1], p[2],
            self.crc8_val,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> "LoRaPublish":
        if len(buf) < cls.SIZE:
            raise ValueError(f"buffer too short: {len(buf)} < {cls.SIZE}")
        f = struct.unpack_from(cls._FMT, buf)
        header  = LoRaHeader(f[0], f[1], f[2], f[3], f[4])
        payload = bytes(f[7:10])
        return cls(header, topic=f[5], pld_len=f[6], payload=payload, crc8_val=f[10])

    def verify_crc(self) -> bool:
        h = self.header
        p = (self.payload + bytes(LP_MAX_PAYLOAD))[:LP_MAX_PAYLOAD]
        expected = crc8(h.pack() + bytes([self.topic, self.pld_len]) + p)
        return expected == self.crc8_val

    @property
    def valid_payload(self) -> bytes:
        """Returns only the meaningful payload bytes (first pld_len bytes)."""
        return self.payload[:self.pld_len]

    def is_alert(self) -> bool:
        return self.topic == Topic.ALERT


# ── LoRaAck  7 bytes ──────────────────────────────────────────────
@dataclass
class LoRaAck:
    header:     LoRaHeader
    ack_msg_id: int
    crc8_val:   int
    # ── 수신 메타데이터 (wire format 외부, serial_reader 가 채움) ──
    rssi: int | None   = field(default=None, compare=False)
    snr:  float | None = field(default=None, compare=False)

    _FMT = "<BBBBBBB"
    SIZE: int = struct.calcsize(_FMT)  # 7

    @classmethod
    def build(cls, node_id: int, msg_id: int,
              ack_msg_id: int, ttl: int = 0) -> "LoRaAck":
        header   = LoRaHeader(LP_PREAMBLE, int(MsgType.ACK), node_id, msg_id, ttl)
        checksum = crc8(header.pack() + bytes([ack_msg_id]))
        return cls(header, ack_msg_id, checksum)

    def pack(self) -> bytes:
        h = self.header
        return struct.pack(
            self._FMT,
            h.preamble, h.msg_type, h.node_id, h.msg_id, h.ttl,
            self.ack_msg_id, self.crc8_val,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> "LoRaAck":
        if len(buf) < cls.SIZE:
            raise ValueError(f"buffer too short: {len(buf)} < {cls.SIZE}")
        f = struct.unpack_from(cls._FMT, buf)
        header = LoRaHeader(f[0], f[1], f[2], f[3], f[4])
        return cls(header, ack_msg_id=f[5], crc8_val=f[6])

    def verify_crc(self) -> bool:
        expected = crc8(self.header.pack() + bytes([self.ack_msg_id]))
        return expected == self.crc8_val


# ── Top-level parser ───────────────────────────────────────────────
def parse_packet(buf: bytes) -> LoRaPublish | LoRaAck | None:
    """Deserialise a raw byte buffer into the appropriate packet type.

    Returns None if the preamble is missing or the buffer is too short.
    """
    if len(buf) < LoRaHeader.SIZE or buf[0] != LP_PREAMBLE:
        return None
    msg_type = buf[1]
    if msg_type in (MsgType.PUBLISH, MsgType.RELAY):
        return LoRaPublish.unpack(buf) if len(buf) >= LoRaPublish.SIZE else None
    if msg_type == MsgType.ACK:
        return LoRaAck.unpack(buf) if len(buf) >= LoRaAck.SIZE else None
    return None
