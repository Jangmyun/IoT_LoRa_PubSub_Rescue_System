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
    TEST_ASSERT_EQUAL_HEX8(NODE_BUOY_B, relayed->header.node_id);
    TEST_ASSERT_EQUAL_UINT8(1, relayed->header.ttl);      // 2 - 1
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

// 12. QoS 1 — ACK 수신 성공 → true 반환
void test_qos1_succeeds_on_ack() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    // 첫 번째 publish의 msg_id는 0
    LoRaAck ack{};
    ack.header.preamble = LP_PREAMBLE;
    ack.header.msg_type = MSG_ACK;
    ack.header.node_id = NODE_PI;
    ack.ack_msg_id = 0;
    LoRa.injectRx(reinterpret_cast<uint8_t*>(&ack), sizeof(LoRaAck));

    uint8_t p[] = { 90 };
    bool ok = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_TRUE(ok);
}

// 13. QoS 1 — ACK 없음 → LP_MAX_RETRIES 후 false 반환
void test_qos1_fails_on_timeout() {
    LoRaPubSub ps(NODE_BUOY_A);
    ps.begin();

    uint8_t p[] = { 90 };
    bool ok = ps.publish(TOPIC_ALERT, p, 1, /*ack_required=*/true);
    TEST_ASSERT_FALSE(ok);
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
}

// ─────────────────────────────────────────────────────────
int main() {
    UNITY_BEGIN();

    RUN_TEST(test_publish_qos0_structure);
    RUN_TEST(test_publish_ttl_initial_value);
    RUN_TEST(test_publish_packet_length);
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
    RUN_TEST(test_sensor_manager_tracks_ready_state);
    RUN_TEST(test_sensor_manager_skips_not_ready_reads);
    RUN_TEST(test_sensor_manager_publish_raw_only_ready_sensors);

    return UNITY_END();
}
