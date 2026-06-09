#pragma once
#include <Arduino.h>

// ── 프로토콜 상수 ──────────────────────────────
#define LP_PREAMBLE       0xAB
#define LP_MAX_TTL        3
#define LP_MAX_RETRIES    3
#define LP_MAX_PAYLOAD    3      // PUBLISH 페이로드 최대 바이트
#define LP_SEEN_BUF       16     // 중복 억제 링버퍼 크기

// ── MSG_TYPE ───────────────────────────────────
#define MSG_PUBLISH       0x01
#define MSG_SUBSCRIBE     0x02
#define MSG_ACK           0x03
#define MSG_RELAY         0x04

// ── TOPIC (상위 니블 = 카테고리) ───────────────
//   0x1x : 경보
//   0x2x : 상태
//   0x3x : 명령 (Pi → 부표)
#define TOPIC_ALERT       0x10   // 익수자 감지, payload: confidence(1B)
#define TOPIC_ALERT_CLEAR 0x11   // 경보 해제,   payload: 없음
#define TOPIC_HEARTBEAT   0x20   // 생존 신호,   payload: battery(1B) status(1B)
#define TOPIC_SENSOR_RAW  0x21   // 디버그 센서, payload: sonar(1B) accel(1B)
#define TOPIC_CMD_RESET   0x30   // 부표 리셋,   payload: 없음
#define TOPIC_CMD_CONFIG  0x31   // 파라미터 설정, payload: interval(1B) threshold(1B)

// ── NODE_ID ────────────────────────────────────
#define NODE_PI           0x00
#define NODE_BUOY_A       0x01
#define NODE_BUOY_B       0x02
#define NODE_BUOY_C       0x03

// ── 패킷 구조체 ────────────────────────────────
#pragma pack(push, 1)

struct LoRaHeader {
    uint8_t preamble;   // 0xAB  — 노이즈 패킷 구분
    uint8_t msg_type;
    uint8_t node_id;
    uint8_t msg_id;     // 0~255 순환, 중복 억제용
    uint8_t ttl;
};                      // 5 bytes

struct LoRaPublish {
    LoRaHeader header;
    uint8_t topic;
    uint8_t pld_len;
    uint8_t payload[LP_MAX_PAYLOAD];
    uint8_t crc8;       // 헤더+topic+pld_len+payload CRC8
};                      // 최대 11 bytes

struct LoRaAck {
    LoRaHeader header;
    uint8_t ack_msg_id;
    uint8_t crc8;
};                      // 7 bytes

#pragma pack(pop)

using LoRaRxCallback = void (*)(const LoRaPublish &pkt);

class LoRaPubSub {
public:
    explicit LoRaPubSub(uint8_t node_id);

    void begin();

    bool publish(uint8_t topic,
                 const uint8_t *payload, uint8_t pld_len,
                 bool ack_required = false);

    void tick();

    void subscribe(uint8_t topic, LoRaRxCallback cb);

private:
    uint8_t  _node_id;
    uint8_t  _msg_id_counter;

    static constexpr uint8_t MAX_SUBS = 8;
    uint8_t         _sub_topics[MAX_SUBS];
    LoRaRxCallback  _sub_cbs[MAX_SUBS];
    uint8_t         _sub_count;

    struct SeenEntry { uint8_t node_id; uint8_t msg_id; };
    SeenEntry _seen[LP_SEEN_BUF];
    uint8_t   _seen_head;

    uint8_t  _nextMsgId();
    uint8_t  _crc8(const uint8_t *data, uint8_t len);
    bool     _alreadySeen(uint8_t node_id, uint8_t msg_id);
    void     _markSeen(uint8_t node_id, uint8_t msg_id);
    void     _relay(const LoRaPublish &pkt);
    void     _sendRaw(const uint8_t *buf, uint8_t len);
    void     _handleIncoming(const LoRaPublish &pkt);
};
