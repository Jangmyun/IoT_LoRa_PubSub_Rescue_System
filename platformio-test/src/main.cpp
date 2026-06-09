#include <Arduino.h>
#include <LoRa.h>
#include "LoRaPubSub.h"

// TTGO LoRa32 핀 정의
#ifndef LORA_SCK
#define LORA_SCK   5
#endif
#ifndef LORA_MISO
#define LORA_MISO  19
#endif
#ifndef LORA_MOSI
#define LORA_MOSI  27
#endif
#ifndef LORA_SS
#define LORA_SS    18
#endif
#ifndef LORA_RST
#define LORA_RST   14
#endif
#ifndef LORA_DI0
#define LORA_DI0   26
#endif

LoRaPubSub pubsub(NODE_BUOY_B);  // 이 보드는 부표 B

void onAlert(const LoRaPublish &pkt) {
    Serial.printf("[SUB] ALERT from node 0x%02X | confidence=%d%%\n",
                  pkt.header.node_id, pkt.payload[0]);
}

void setup() {
    Serial.begin(115200);

    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DI0);

    if (!LoRa.begin(923E6)) {  // 한국 LoRa 주파수: 920~923MHz
        Serial.println("[ERR] LoRa init failed");
        while (1);
    }

    pubsub.begin();
    pubsub.subscribe(TOPIC_ALERT, onAlert);  // 경보 토픽 구독

    Serial.println("[OK] LoRaPubSub ready");
    Serial.printf("     Header: %d bytes\n", sizeof(LoRaHeader));
    Serial.printf("     PUBLISH max: %d bytes\n", sizeof(LoRaPublish));
    Serial.printf("     ACK: %d bytes\n", sizeof(LoRaAck));
}

void loop() {
    pubsub.tick();  // 수신 처리

    // 테스트: 5초마다 하트비트 전송 (QoS 0)
    static uint32_t last_hb = 0;
    if (millis() - last_hb > 5000) {
        uint8_t payload[2] = {75, 0x00};  // battery=75%, status=정상
        pubsub.publish(TOPIC_HEARTBEAT, payload, 2);
        Serial.println("[PUB] Heartbeat");
        last_hb = millis();
    }

    // 테스트: 10초마다 경보 전송 (QoS 1, ACK 대기)
    static uint32_t last_alert = 0;
    if (millis() - last_alert > 10000) {
        uint8_t payload[1] = {90};  // confidence=90%
        bool ok = pubsub.publish(TOPIC_ALERT, payload, 1, true);
        Serial.printf("[PUB] ALERT → %s\n", ok ? "ACK OK" : "FAILED");
        last_alert = millis();
    }
}