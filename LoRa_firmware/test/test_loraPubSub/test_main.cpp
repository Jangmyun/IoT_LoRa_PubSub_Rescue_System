#include <unity.h>
#include <LoRa.h>        // MockLoRa 정의 (mocks/LoRa.h)
#include "LoRaPubSub.h"
#include "SensorManager.h"

// ── 글로벌 mock 인스턴스 ──────────────────────────────────
uint32_t _mock_millis = 0;
MockLoRa LoRa;

// ── 헬퍼 ─────────────────────────────────────────────────
static LoRaPublish make_publish(uint8_t node_id, uint8_t msg_id,
    uint8_t topic,
    const uint8_t* payload, uint8_t pld_len,
    uint8_t ttl = LP_MAX_TTL)
{
    LoRaPublish pkt{};
    pkt.header.preamble = LP_PREAMBLE;
    pkt.header.msg_type = MSG_PUBLISH;
    pkt.header.node_id = node_id;
    pkt.header.msg_id = msg_id;
    pkt.header.ttl = ttl;
    pkt.topic = topic;
    pkt.pld_len = pld_len;
    if (pld_len && payload) memcpy(pkt.payload, payload, pld_len);
    return pkt;
}

static uint8_t crc8_for_test(const uint8_t* data, uint8_t len) {
    uint8_t crc = 0x00;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++) {
            crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
        }
    }
    return crc;
}

static void assert_compact_publish_crc(uint8_t payload_len) {
    uint8_t crc_offset = sizeof(LoRaHeader) + 2 + payload_len;

    TEST_ASSERT_EQUAL_INT((int)crc_offset + 1, LoRa.tx_len);
    TEST_ASSERT_EQUAL_HEX8(crc8_for_test(LoRa.tx_buf, crc_offset), LoRa.tx_buf[crc_offset]);
}

// ── 콜백 스파이 ───────────────────────────────────────────
static int         spy_count;
static LoRaPublish spy_pkt;

static void spy_cb(const LoRaPublish& pkt) {
    spy_count++;
    spy_pkt = pkt;
}

// ── 픽스처 ───────────────────────────────────────────────
void setUp() { _mock_millis = 0; LoRa.reset(); spy_count = 0; }
void tearDown() {}

// ─────────────────────────────────────────────────────────
// 1. QoS 0 publish — 패킷 구조 검증
// ─────────────────────────────────────────────────────────
void test_publish_qos0_structure() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1);

    TEST_ASSERT_GREATER_THAN(0, LoRa.tx_len);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_HEX8(LP_PREAMBLE, sent->header.preamble);
    TEST_ASSERT_EQUAL_HEX8(MSG_PUBLISH, sent->header.msg_type);
    TEST_ASSERT_EQUAL_HEX8(NODE_BUOY_A, sent->header.node_id);
    TEST_ASSERT_EQUAL_HEX8(TOPIC_ALERT, sent->topic);
    TEST_ASSERT_EQUAL_UINT8(1, sent->pld_len);
    TEST_ASSERT_EQUAL_UINT8(90, sent->payload[0]);
}

// 2. TTL 초기값 = LP_MAX_TTL
void test_publish_ttl_initial_value() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 1 };
    ps.publish(TOPIC_HEARTBEAT, p, 1);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_UINT8(LP_MAX_TTL, sent->header.ttl);
}

// 3. 전송 바이트 수 = sizeof(header)+topic+pld_len+payload+crc8
void test_publish_packet_length() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 42 };
    ps.publish(TOPIC_ALERT, p, 1);

    // 5(header) + 1(topic) + 1(pld_len) + 1(payload) + 1(crc8) = 9
    TEST_ASSERT_EQUAL_INT(9, LoRa.tx_len);
}

void test_publish_crc_after_empty_payload() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    ps.publish(TOPIC_ALERT_CLEAR, nullptr, 0);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_HEX8(TOPIC_ALERT_CLEAR, sent->topic);
    TEST_ASSERT_EQUAL_UINT8(0, sent->pld_len);
    assert_compact_publish_crc(0);
}

void test_publish_crc_after_one_byte_payload() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_UINT8(90, sent->payload[0]);
    assert_compact_publish_crc(1);
}

void test_publish_crc_after_two_byte_payload() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 75, 0 };
    ps.publish(TOPIC_HEARTBEAT, p, 2);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_UINT8(75, sent->payload[0]);
    TEST_ASSERT_EQUAL_UINT8(0, sent->payload[1]);
    assert_compact_publish_crc(2);
}

void test_publish_crc_after_full_payload() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 1, 2, 3 };
    ps.publish(TOPIC_SENSOR_RAW, p, 3);

    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_UINT8(3, sent->pld_len);
    TEST_ASSERT_EQUAL_UINT8(3, sent->payload[2]);
    assert_compact_publish_crc(3);
}

// 4. msg_id 카운터 단조 증가
void test_msg_id_increments() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 1 };
    ps.publish(TOPIC_HEARTBEAT, p, 1);
    uint8_t id0 = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf)->header.msg_id;

    LoRa.reset();
    ps.publish(TOPIC_HEARTBEAT, p, 1);
    uint8_t id1 = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf)->header.msg_id;

    TEST_ASSERT_EQUAL_UINT8((uint8_t)(id0 + 1), id1);
}

// 5. 구독 콜백 — 정확한 토픽 일치
void test_subscribe_exact_topic_fires() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();
    ps.subscribe(TOPIC_ALERT, spy_cb);

    uint8_t p[] = { 80 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 0, TOPIC_ALERT, p, 1);
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_EQUAL_INT(1, spy_count);
    TEST_ASSERT_EQUAL_HEX8(NODE_BUOY_A, spy_pkt.header.node_id);
    TEST_ASSERT_EQUAL_UINT8(80, spy_pkt.payload[0]);
}

// 6. 구독 콜백 — 상위 니블 와일드카드 매칭
//    subscribe(0x10) → TOPIC_ALERT_CLEAR(0x11)도 수신
void test_subscribe_upper_nibble_wildcard() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();
    ps.subscribe(0x10, spy_cb);  // 카테고리 0x1x 전체

    uint8_t p[] = { 0 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 1, TOPIC_ALERT_CLEAR, p, 1);
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_EQUAL_INT(1, spy_count);
}

// 7. 중복 패킷 억제 — 동일 {node_id, msg_id}는 한 번만 처리
void test_duplicate_packet_suppressed() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();
    ps.subscribe(TOPIC_ALERT, spy_cb);

    uint8_t p[] = { 70 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 42, TOPIC_ALERT, p, 1);

    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();
    TEST_ASSERT_EQUAL_INT(1, spy_count);

    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();
    TEST_ASSERT_EQUAL_INT(1, spy_count);  // 여전히 1
}

// 8. 자신이 보낸 패킷(node_id 일치) 무시
void test_self_packet_ignored() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();
    ps.subscribe(TOPIC_ALERT, spy_cb);

    uint8_t p[] = { 60 };
    LoRaPublish pkt = make_publish(NODE_BUOY_B, 10, TOPIC_ALERT, p, 1);
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_EQUAL_INT(0, spy_count);
}

// 9. 유효하지 않은 preamble 무시
void test_invalid_preamble_ignored() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();
    ps.subscribe(TOPIC_ALERT, spy_cb);

    uint8_t p[] = { 60 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 20, TOPIC_ALERT, p, 1);
    pkt.header.preamble = 0xFF;
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_EQUAL_INT(0, spy_count);
}

// 10. 멀티홉 릴레이 — TTL 감소 및 MSG_RELAY 전환
void test_relay_decrements_ttl_and_type() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();

    uint8_t p[] = { 50 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 30, TOPIC_ALERT, p, 1, /*ttl=*/2);
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_GREATER_THAN(0, LoRa.tx_len);

    auto* relayed = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_HEX8(MSG_RELAY, relayed->header.msg_type);
    // 릴레이는 원본 발신자 node_id(A)를 그대로 보존해야 한다
    TEST_ASSERT_EQUAL_HEX8(NODE_BUOY_A, relayed->header.node_id);
    TEST_ASSERT_EQUAL_UINT8(1, relayed->header.ttl);      // 2 - 1
    assert_compact_publish_crc(1);
}

// 11. TTL=1 이면 릴레이하지 않음
void test_no_relay_when_ttl_is_one() {
    LoRaPubSub ps(NODE_BUOY_B);
    ps.begin();

    uint8_t p[] = { 50 };
    LoRaPublish pkt = make_publish(NODE_BUOY_A, 31, TOPIC_ALERT, p, 1, /*ttl=*/1);
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&pkt), sizeof(LoRaPublish));
    ps.tick();

    TEST_ASSERT_EQUAL_INT(0, LoRa.tx_len);
}

// 12. QoS 1 — enqueue 후 tick()에서 ACK 수신 → outbox 비워짐
void test_qos1_succeeds_on_ack() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    bool enqueued = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_TRUE(enqueued);
    TEST_ASSERT_EQUAL_UINT8(1, ps.outboxCount());

    // 첫 번째 publish의 msg_id = 0 인 ACK 주입
    LoRaAck ack{};
    ack.header.preamble = LP_PREAMBLE;
    ack.header.msg_type = MSG_ACK;
    ack.header.node_id  = NODE_PI;
    ack.ack_msg_id      = 0;
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&ack), sizeof(LoRaAck));

    ps.tick(); // ACK 수신 → _ackOutbox(0) → 슬롯 해제
    TEST_ASSERT_EQUAL_UINT8(0, ps.outboxCount());
}

// 13. QoS 1 — ACK 없음 → LP_MAX_RETRIES 소진 후 드롭
void test_qos1_fails_on_timeout() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    bool enqueued = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_TRUE(enqueued);

    // 각 tick 사이에 LP_ACK_TIMEOUT_MS(800ms) 초과분을 수동으로 경과시킨다.
    // retry_count: 0→1 (tick1), 1→2 (tick2), 2→3 (tick3), 3>=MAX → 드롭 (tick4)
    ps.tick();             // 첫 전송 (retry_count 0→1)
    _mock_millis += 900;
    ps.tick();             // 타임아웃 재전송 (1→2)
    _mock_millis += 900;
    ps.tick();             // 타임아웃 재전송 (2→3)
    _mock_millis += 900;
    ps.tick();             // retry_count >= LP_MAX_RETRIES → 드롭

    TEST_ASSERT_EQUAL_UINT8(0, ps.outboxCount());
}

// T14. outbox enqueue — publish() true 반환, outboxCount 증가
void test_outbox_enqueue_returns_true() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 80 };
    bool ok = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_TRUE(ok);
    TEST_ASSERT_EQUAL_UINT8(1, ps.outboxCount());
}

// T15. outbox 가득 참 → publish() false 반환
void test_outbox_full_returns_false() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 80 };
    for (uint8_t i = 0; i < LP_OUTBOX_SIZE; i++) {
        bool ok = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
        TEST_ASSERT_TRUE(ok);
    }
    TEST_ASSERT_EQUAL_UINT8(LP_OUTBOX_SIZE, ps.outboxCount());

    bool overflow = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_FALSE(overflow);
    TEST_ASSERT_EQUAL_UINT8(LP_OUTBOX_SIZE, ps.outboxCount());
}

// T16. 첫 tick()에서 outbox 패킷이 실제로 전송된다
void test_outbox_sends_on_first_tick() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);

    LoRa.reset(); // publish 중 beginPacket으로 쌓인 tx 초기화
    ps.tick();    // _processOutbox → _sendPublish 호출 기대

    TEST_ASSERT_GREATER_THAN(0, LoRa.tx_len);
    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_HEX8(TOPIC_ALERT, sent->topic);
    TEST_ASSERT_EQUAL_UINT8(90, sent->payload[0]);
}

// T17. ACK 수신 시 outbox 슬롯이 해제된다
void test_outbox_cleared_on_ack() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    ps.tick(); // 전송 (retry_count 0→1)

    LoRaAck ack{};
    ack.header.preamble = LP_PREAMBLE;
    ack.header.msg_type = MSG_ACK;
    ack.header.node_id  = NODE_PI;
    ack.ack_msg_id      = 0;
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&ack), sizeof(LoRaAck));

    ps.tick(); // ACK 처리 → 슬롯 해제
    TEST_ASSERT_EQUAL_UINT8(0, ps.outboxCount());
}

// T18. ACK 없이 재전송 후 LP_MAX_RETRIES 초과 시 자동 드롭
void test_outbox_retransmits_then_drops() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);

    ps.tick();           // 첫 전송 (retry 0→1)
    _mock_millis += 900; // 800ms 초과
    ps.tick();           // 재전송 (1→2)
    _mock_millis += 900;
    ps.tick();           // 재전송 (2→3)
    _mock_millis += 900;
    ps.tick();           // 3 >= LP_MAX_RETRIES → 드롭

    TEST_ASSERT_EQUAL_UINT8(0, ps.outboxCount());
}

// T19. 잘못된 ack_msg_id는 outbox 슬롯을 해제하지 않는다
void test_outbox_ack_wrong_msg_id_ignored() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true); // msg_id = 0
    ps.tick(); // 전송

    // 다른 msg_id로 ACK 주입
    LoRaAck ack{};
    ack.header.preamble = LP_PREAMBLE;
    ack.header.msg_type = MSG_ACK;
    ack.header.node_id  = NODE_PI;
    ack.ack_msg_id      = 99; // 존재하지 않는 msg_id
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&ack), sizeof(LoRaAck));

    ps.tick();
    TEST_ASSERT_EQUAL_UINT8(1, ps.outboxCount()); // 슬롯 유지

    // 올바른 ACK 주입
    ack.ack_msg_id = 0;
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&ack), sizeof(LoRaAck));
    ps.tick();
    TEST_ASSERT_EQUAL_UINT8(0, ps.outboxCount()); // 이제 해제
}

class FakeSensor : public ISensor {
public:
    FakeSensor(bool begin_result, bool read_result, uint8_t packed)
        : begin_result(begin_result), read_result(read_result), packed(packed) {}

    bool begin() override {
        begin_calls++;
        return begin_result;
    }

    bool read() override {
        read_calls++;
        return read_result;
    }

    float getValue() override { return 0.0f; }
    uint8_t getPacked() override { return packed; }

    bool begin_result;
    bool read_result;
    uint8_t packed;
    int begin_calls = 0;
    int read_calls = 0;
};

void test_sensor_manager_tracks_ready_state() {
    SensorManager manager;
    FakeSensor ready(true, true, 10);
    FakeSensor missing(false, true, 20);

    manager.attach(&ready);
    manager.attach(&missing);
    manager.attach(nullptr);

    TEST_ASSERT_EQUAL_UINT8(2, manager.count());
    TEST_ASSERT_EQUAL_UINT8(1, manager.beginAll());
    TEST_ASSERT_EQUAL_UINT8(1, manager.readyCount());
    TEST_ASSERT_TRUE(manager.isReady(0));
    TEST_ASSERT_FALSE(manager.isReady(1));
    TEST_ASSERT_FALSE(manager.isReady(2));
    TEST_ASSERT_EQUAL_INT(1, ready.begin_calls);
    TEST_ASSERT_EQUAL_INT(1, missing.begin_calls);
}

void test_sensor_manager_skips_not_ready_reads() {
    SensorManager manager;
    FakeSensor ready(true, true, 10);
    FakeSensor missing(false, true, 20);

    manager.attach(&ready);
    manager.attach(&missing);
    manager.beginAll();

    TEST_ASSERT_EQUAL_UINT8(1, manager.readAll());
    TEST_ASSERT_EQUAL_INT(1, ready.read_calls);
    TEST_ASSERT_EQUAL_INT(0, missing.read_calls);
}

void test_sensor_manager_publish_raw_only_ready_sensors() {
    SensorManager manager;
    FakeSensor missing(false, true, 99);
    FakeSensor ready(true, true, 42);
    LoRaPubSub ps(NODE_BUOY_A);

    ps.begin();
    manager.attach(&missing);
    manager.attach(&ready);
    manager.beginAll();
    manager.publishRaw(ps);

    TEST_ASSERT_GREATER_THAN(0, LoRa.tx_len);
    auto* sent = reinterpret_cast<LoRaPublish*>(LoRa.tx_buf);
    TEST_ASSERT_EQUAL_HEX8(TOPIC_SENSOR_RAW, sent->topic);
    TEST_ASSERT_EQUAL_UINT8(1, sent->pld_len);
    TEST_ASSERT_EQUAL_UINT8(42, sent->payload[0]);
    assert_compact_publish_crc(1);
}

// ─────────────────────────────────────────────────────────
int main() {
    UNITY_BEGIN();

    RUN_TEST(test_publish_qos0_structure);
    RUN_TEST(test_publish_ttl_initial_value);
    RUN_TEST(test_publish_packet_length);
    RUN_TEST(test_publish_crc_after_empty_payload);
    RUN_TEST(test_publish_crc_after_one_byte_payload);
    RUN_TEST(test_publish_crc_after_two_byte_payload);
    RUN_TEST(test_publish_crc_after_full_payload);
    RUN_TEST(test_msg_id_increments);
    RUN_TEST(test_subscribe_exact_topic_fires);
    RUN_TEST(test_subscribe_upper_nibble_wildcard);
    RUN_TEST(test_duplicate_packet_suppressed);
    RUN_TEST(test_self_packet_ignored);
    RUN_TEST(test_invalid_preamble_ignored);
    RUN_TEST(test_relay_decrements_ttl_and_type);
    RUN_TEST(test_no_relay_when_ttl_is_one);
    RUN_TEST(test_qos1_succeeds_on_ack);
    RUN_TEST(test_qos1_fails_on_timeout);
    RUN_TEST(test_outbox_enqueue_returns_true);
    RUN_TEST(test_outbox_full_returns_false);
    RUN_TEST(test_outbox_sends_on_first_tick);
    RUN_TEST(test_outbox_cleared_on_ack);
    RUN_TEST(test_outbox_retransmits_then_drops);
    RUN_TEST(test_outbox_ack_wrong_msg_id_ignored);
    RUN_TEST(test_sensor_manager_tracks_ready_state);
    RUN_TEST(test_sensor_manager_skips_not_ready_reads);
    RUN_TEST(test_sensor_manager_publish_raw_only_ready_sensors);

    return UNITY_END();
}
