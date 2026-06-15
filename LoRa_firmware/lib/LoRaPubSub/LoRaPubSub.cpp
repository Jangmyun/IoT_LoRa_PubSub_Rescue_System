#include "LoRaPubSub.h"
#include <LoRa.h>

LoRaPubSub::LoRaPubSub(uint8_t node_id)
    : _node_id(node_id), _msg_id_counter(0),
    _sub_count(0), _seen_head(0)
{
    memset(_sub_topics, 0, sizeof(_sub_topics));
    memset(_sub_cbs, 0, sizeof(_sub_cbs));
    memset(_seen, 0, sizeof(_seen));
    memset(_outbox, 0, sizeof(_outbox));
}

void LoRaPubSub::begin() {
    // LoRa.begin()은 main.cpp에서 먼저 호출
    LoRa.setSyncWord(0xAB);   // 모든 노드·게이트웨이 동일 값으로 고정
    LoRa.receive();
}

bool LoRaPubSub::publish(uint8_t topic,
    const uint8_t* payload, uint8_t pld_len,
    bool ack_required)
{
    if (payload == nullptr) pld_len = 0;
    if (pld_len > LP_MAX_PAYLOAD) pld_len = LP_MAX_PAYLOAD;

    LoRaPublish pkt{};
    pkt.header.preamble = LP_PREAMBLE;
    pkt.header.msg_type = MSG_PUBLISH;
    pkt.header.node_id = _node_id;
    pkt.header.msg_id = _nextMsgId();
    pkt.header.ttl = LP_MAX_TTL;
    pkt.topic = topic;
    pkt.pld_len = pld_len;
    if (pld_len > 0) memcpy(pkt.payload, payload, pld_len);

    if (!ack_required) {
        _sendPublish(pkt);
        return true;
    }

    // QoS 1: outbox에 enqueue하고 즉시 반환 (non-blocking).
    // tick()에서 ACK 수신 시 해제하고, 타임아웃 시 재전송·만료 시 드롭한다.
    return _enqueue(pkt);
}

void LoRaPubSub::subscribe(uint8_t topic, LoRaRxCallback cb) {
    if (_sub_count >= MAX_SUBS) return;
    _sub_topics[_sub_count] = topic;
    _sub_cbs[_sub_count] = cb;
    _sub_count++;
}

void LoRaPubSub::tick() {
    int size = LoRa.parsePacket();

    // ACK(7B)와 PUBLISH 최소(8B) 중 작은 값으로 하한을 설정
    if (size >= (int)sizeof(LoRaAck)) {
        LoRaPublish pkt{};
        LoRa.readBytes(reinterpret_cast<uint8_t*>(&pkt),
            min((int)sizeof(LoRaPublish), size));

        if (pkt.header.preamble == LP_PREAMBLE &&
            pkt.header.node_id != _node_id)
        {
            if (pkt.header.msg_type == MSG_ACK) {
                // ACK는 중복 억제 대상이 아님 — outbox에서 해당 msg_id 슬롯을 해제
                const LoRaAck* ack = reinterpret_cast<const LoRaAck*>(&pkt);
                _ackOutbox(ack->ack_msg_id);
            } else if ((pkt.header.msg_type == MSG_PUBLISH ||
                        pkt.header.msg_type == MSG_RELAY) &&
                       size >= (int)(sizeof(LoRaHeader) + 3)) {
                if (!_alreadySeen(pkt.header.node_id, pkt.header.msg_id)) {
                    _markSeen(pkt.header.node_id, pkt.header.msg_id);
                    _handleIncoming(pkt);
                    if (pkt.header.ttl > 1) _relay(pkt);
                }
            }
        }
    }

    _processOutbox();
}

void LoRaPubSub::_handleIncoming(const LoRaPublish& pkt) {
    for (uint8_t i = 0; i < _sub_count; i++) {
        if (_sub_topics[i] == pkt.topic ||
            _sub_topics[i] == (pkt.topic & 0xF0)) {
            _sub_cbs[i](pkt);
        }
    }
}

void LoRaPubSub::_relay(const LoRaPublish& pkt) {
    LoRaPublish relay = pkt;
    relay.header.msg_type = MSG_RELAY;
    // node_id는 원본 발신자 ID 그대로 유지 — 변경 시 게이트웨이가 릴레이어 노드 데이터로 오인함
    relay.header.ttl--;
    _sendPublish(relay);
}

void LoRaPubSub::_sendPublish(LoRaPublish& pkt) {
    if (pkt.pld_len > LP_MAX_PAYLOAD) pkt.pld_len = LP_MAX_PAYLOAD;

    constexpr uint8_t header_len = sizeof(LoRaHeader);
    uint8_t crc_offset = header_len + 2 + pkt.pld_len;
    uint8_t wire[sizeof(LoRaPublish)] = {};

    memcpy(wire, &pkt.header, header_len);
    wire[header_len]     = pkt.topic;
    wire[header_len + 1] = pkt.pld_len;
    if (pkt.pld_len > 0) memcpy(wire + header_len + 2, pkt.payload, pkt.pld_len);

    pkt.crc8 = _crc8(wire, crc_offset);
    wire[crc_offset] = pkt.crc8;
    _sendRaw(wire, crc_offset + 1);
}

void LoRaPubSub::_sendRaw(const uint8_t* buf, uint8_t len) {
    LoRa.beginPacket();
    LoRa.write(buf, len);
    LoRa.endPacket();
    LoRa.receive();
}

uint8_t LoRaPubSub::_nextMsgId() {
    return _msg_id_counter++;
}

bool LoRaPubSub::_alreadySeen(uint8_t node_id, uint8_t msg_id) {
    for (uint8_t i = 0; i < LP_SEEN_BUF; i++)
        if (_seen[i].node_id == node_id && _seen[i].msg_id == msg_id)
            return true;
    return false;
}

void LoRaPubSub::_markSeen(uint8_t node_id, uint8_t msg_id) {
    _seen[_seen_head] = { node_id, msg_id };
    _seen_head = (_seen_head + 1) % LP_SEEN_BUF;
}

uint8_t LoRaPubSub::_crc8(const uint8_t* data, uint8_t len) {
    uint8_t crc = 0x00;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
    }
    return crc;
}

bool LoRaPubSub::_enqueue(const LoRaPublish& pkt) {
    for (uint8_t i = 0; i < LP_OUTBOX_SIZE; i++) {
        if (!_outbox[i].in_use) {
            _outbox[i].pkt          = pkt;
            _outbox[i].last_sent_ms = 0;
            _outbox[i].retry_count  = 0;
            _outbox[i].in_use       = true;
            return true;
        }
    }
    return false; // outbox 가득 참
}

void LoRaPubSub::_ackOutbox(uint8_t ack_msg_id) {
    for (uint8_t i = 0; i < LP_OUTBOX_SIZE; i++) {
        if (_outbox[i].in_use &&
            _outbox[i].pkt.header.msg_id == ack_msg_id) {
            _outbox[i].in_use = false;
            return;
        }
    }
}

void LoRaPubSub::_processOutbox() {
    for (uint8_t i = 0; i < LP_OUTBOX_SIZE; i++) {
        if (!_outbox[i].in_use) continue;

        OutboxEntry& e = _outbox[i];

        if (e.retry_count >= LP_MAX_RETRIES) {
            e.in_use = false; // 최대 재전송 초과 → 드롭
            continue;
        }

        bool first   = (e.retry_count == 0);
        bool timeout = (millis() - e.last_sent_ms >= LP_ACK_TIMEOUT_MS);

        if (first || timeout) {
            _sendPublish(e.pkt);
            e.last_sent_ms = millis();
            e.retry_count++;
            return; // 이번 tick에서 1개만 전송 (채널 충돌 방지)
        }
    }
}

uint8_t LoRaPubSub::outboxCount() const {
    uint8_t cnt = 0;
    for (uint8_t i = 0; i < LP_OUTBOX_SIZE; i++)
        if (_outbox[i].in_use) cnt++;
    return cnt;
}
