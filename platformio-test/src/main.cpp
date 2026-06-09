#include <Arduino.h>
#include <LoRa.h>
#include "LoRaPubSub.h"
#include "SensorManager.h"
#include "SonarSensor.h"
#include "ImuSensor.h"

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

LoRaPubSub    pubsub(NODE_BUOY_B);
SonarSensor   sonar(13, 12);   // TRIG=GPIO13, ECHO=GPIO12
ImuSensor     imu;             // I2C SDA=GPIO21, SCL=GPIO22
SensorManager sensors;

static bool lora_ok = false;   // LoRa 초기화 성공 여부, LoRa 관련 코드 전체 가드용

void onAlert(const LoRaPublish& pkt) {
    Serial.printf("[SUB] ALERT from node 0x%02X | confidence=%d%%\n",
                  pkt.header.node_id, pkt.payload[0]);
}

void setup() {
    Serial.begin(115200);
    delay(1000);                           // Wokwi 터미널 연결 대기
    Serial.println("[BOOT] starting...");
    Serial.flush();                        // 버퍼 강제 출력

    // Serial 확인 후 LoRa 초기화
    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DI0);

    lora_ok = LoRa.begin(923E6);
    if (lora_ok) {
        pubsub.begin();
        pubsub.subscribe(TOPIC_ALERT, onAlert);
        Serial.println("[OK] LoRa ready");
    } else {
        // Wokwi 시뮬레이션: SX1276 칩 없음 → 센서 전용 모드로 동작
        Serial.println("[WARN] LoRa not found — sensor-only mode (Wokwi?)");
    }

    sensors.attach(&sonar);
    sensors.attach(&imu);
    sensors.beginAll();

    Serial.printf("[OK] sensors: %d attached\n", sensors.count());
    Serial.printf("     LoRaPublish max: %d bytes\n", sizeof(LoRaPublish));
}

void loop() {
    if (lora_ok) pubsub.tick();

    // 3초마다 센서 읽기
    static uint32_t last_sensor = 0;
    if (millis() - last_sensor > 3000) {
        sensors.readAll();
        Serial.printf("[SENSOR] sonar=%.1f cm  |  accel=%.2f m/s2\n",
                      sonar.getValue(), imu.getValue());
        if (lora_ok) sensors.publishRaw(pubsub);
        last_sensor = millis();
    }

    if (!lora_ok) return;  // 아래는 LoRa 필요 구간

    // 5초마다 하트비트 (QoS 0)
    static uint32_t last_hb = 0;
    if (millis() - last_hb > 5000) {
        uint8_t payload[2] = {75, 0x00};
        pubsub.publish(TOPIC_HEARTBEAT, payload, 2);
        Serial.println("[PUB] Heartbeat");
        last_hb = millis();
    }

    // 10초마다 경보 (QoS 1)
    static uint32_t last_alert = 0;
    if (millis() - last_alert > 10000) {
        uint8_t payload[1] = {90};
        bool ok = pubsub.publish(TOPIC_ALERT, payload, 1, true);
        Serial.printf("[PUB] ALERT -> %s\n", ok ? "ACK OK" : "FAILED");
        last_alert = millis();
    }
}
