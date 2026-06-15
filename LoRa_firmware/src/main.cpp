#include <Arduino.h>
#include <LoRa.h>
#include "LoRaPubSub.h"
#include "SensorManager.h"
#include "SonarSensor.h"
#include "ImuSensor.h"
#include <math.h>

// TTGO LoRa32 핀 정의
#ifndef LORA_SCK
#define LORA_SCK 5
#endif
#ifndef LORA_MISO
#define LORA_MISO 19
#endif
#ifndef LORA_MOSI
#define LORA_MOSI 27
#endif
#ifndef LORA_SS
#define LORA_SS 18
#endif
#ifndef LORA_RST
#define LORA_RST 14
#endif
#ifndef LORA_DI0
#define LORA_DI0 26
#endif

#define NODE_ID NODE_BUOY_A // ← 업로드 전 여기만 변경

#ifndef CSV_LOG_ENABLED
#define CSV_LOG_ENABLED 1
#endif

#ifndef SENSOR_SAMPLE_INTERVAL_MS
#define SENSOR_SAMPLE_INTERVAL_MS 100
#endif

#ifndef LORA_RAW_PUBLISH_INTERVAL_MS
#define LORA_RAW_PUBLISH_INTERVAL_MS 3000
#endif

#ifndef DEMO_HEARTBEAT_ENABLED
#define DEMO_HEARTBEAT_ENABLED 1
#endif

#ifndef DEMO_ALERT_ENABLED
#define DEMO_ALERT_ENABLED 0
#endif

#ifndef DATASET_LABEL
#define DATASET_LABEL ""
#endif

// 센서 한 개라도 연속 read 실패가 임계치를 넘으면 relay 전용 모드로 강등한다.
#ifndef SENSOR_FAULT_THRESHOLD
#define SENSOR_FAULT_THRESHOLD 5
#endif

// 부팅 후 센서 begin() 재시도 허용 시간. 이 안에 성공하면 relay-only 진입 안 함.
#ifndef SENSOR_GRACE_PERIOD_MS
#define SENSOR_GRACE_PERIOD_MS 10000
#endif

// Heartbeat status 바이트의 강등 비트.
#define HB_STATUS_DEGRADED 0x01

LoRaPubSub pubsub(NODE_ID);
SonarSensor sonar(13, 12); // TRIG=GPIO13, ECHO=GPIO12
ImuSensor imu;             // I2C SDA=GPIO21, SCL=GPIO22
SensorManager sensors;

static bool lora_ok = false;          // LoRa 초기화 성공 여부, LoRa 관련 코드 전체 가드용
static bool relay_only_mode = false;  // 센서 고장 시 latch: heartbeat + relay만 송신
static uint8_t sonar_fail_streak = 0; // 초음파 연속 read 실패 카운트
static uint8_t imu_fail_streak = 0;   // 가속도 연속 read 실패 카운트

static void enterRelayOnlyMode(const char *reason)
{
    if (relay_only_mode) return;
    relay_only_mode = true;
    Serial.printf("[DEGRADE] entering relay-only mode: %s\n", reason);
}

static void printCsvHeader()
{
#if CSV_LOG_ENABLED
    Serial.println("CSV,timestamp_ms,buoy_id,sonar_cm,accel_mag_ms2,sonar_valid,sonar_timeout,label");
#endif
}

static void printSensorCsv(bool sonar_ok, bool imu_ok)
{
#if CSV_LOG_ENABLED
    const float sonar_cm = sonar.getValue();
    const float accel_ms2 = imu_ok ? imu.getValue() : NAN;
    Serial.printf("CSV,%lu,%u,%.2f,%.3f,%u,%u,%s\n",
                  millis(),
                  NODE_ID,
                  sonar_cm,
                  accel_ms2,
                  sonar_ok ? 1 : 0,
                  sonar_ok ? 0 : 1,
                  DATASET_LABEL);
#endif
}

void onAlert(const LoRaPublish &pkt)
{
    Serial.printf("[SUB] ALERT from node 0x%02X | confidence=%d%%\n",
                  pkt.header.node_id, pkt.payload[0]);
}

void setup()
{
    Serial.begin(115200);
    delay(1000); // Wokwi 터미널 연결 대기
    Serial.println("[BOOT] starting...");
    Serial.flush(); // 버퍼 강제 출력

    // Serial 확인 후 LoRa 초기화
    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DI0);

    lora_ok = LoRa.begin(923E6);
    if (lora_ok)
    {
        pubsub.begin();
        pubsub.subscribe(TOPIC_ALERT, onAlert);
        Serial.println("[OK] LoRa ready (frequency=923 MHz)");
    }
    else
    {
        // Wokwi 시뮬레이션: SX1276 칩 없음 → 센서 전용 모드로 동작
        Serial.println("[WARN] LoRa not found — sensor-only mode (Wokwi?)");
    }

    sensors.attach(&sonar);
    sensors.attach(&imu);
    uint8_t sensors_ready = sensors.beginAll();

    Serial.printf("[INFO] sensors configured: %d software objects\n", sensors.count());
    Serial.printf("[INFO] sensors startup checks passed: %d/%d\n",
                  sensors_ready, sensors.count());
    Serial.println(sensors.isReady(0)
                       ? "[OK] Sonar pins configured (TRIG=GPIO13, ECHO=GPIO12; distance validates on read)"
                       : "[WARN] Sonar pin setup failed — will retry for grace period");
    Serial.println(sensors.isReady(1)
                       ? "[OK] IMU detected on I2C (MPU6050, SDA=GPIO21, SCL=GPIO22)"
                       : "[WARN] IMU not detected on I2C — will retry for grace period");
    Serial.printf("[INFO] LoRaPublish max: %d bytes\n", sizeof(LoRaPublish));
    Serial.printf("[INFO] sensor sample interval: %d ms\n", SENSOR_SAMPLE_INTERVAL_MS);
    Serial.println(DEMO_ALERT_ENABLED
                       ? "[INFO] demo alert publisher enabled"
                       : "[INFO] demo alert publisher disabled");
    printCsvHeader();
}

void loop()
{
    if (lora_ok)
        pubsub.tick(); // relay 처리는 강등 여부와 무관하게 항상 수행

    // ── 센서 grace period 재시도 ─────────────────────────────────────
    // setup()에서 begin()이 실패한 센서를 500ms마다 재시도한다.
    // SENSOR_GRACE_PERIOD_MS 내에 성공하면 정상 모드 유지.
    // 만료 시에도 실패한 센서가 남으면 그 때 relay-only로 latch한다.
    static bool sensor_grace_done = false;
    if (!sensor_grace_done) {
        if (sensors.readyCount() < sensors.count()) {
            if (millis() <= SENSOR_GRACE_PERIOD_MS) {
                static uint32_t last_begin_retry = 0;
                if (millis() - last_begin_retry >= 500) {
                    uint8_t recovered = sensors.retryFailed();
                    if (recovered > 0)
                        Serial.printf("[INFO] %d sensor(s) recovered during grace period\n", recovered);
                    last_begin_retry = millis();
                }
            } else {
                sensor_grace_done = true;
                if (!sensors.isReady(0)) enterRelayOnlyMode("sonar begin timeout");
                if (!sensors.isReady(1)) enterRelayOnlyMode("imu begin timeout");
            }
        } else {
            sensor_grace_done = true;
        }
    }

    // 학습 데이터 수집용: 2초 feature window를 만들 수 있도록 10Hz raw sample을 남긴다.
    // 강등 후에는 센서 read/CSV/raw publish를 모두 건너뛴다.
    static uint32_t last_sensor = 0;
    if (!relay_only_mode && millis() - last_sensor >= SENSOR_SAMPLE_INTERVAL_MS)
    {
        bool sonar_ok = sensors.isReady(0) && sonar.read();
        bool imu_ok = sensors.isReady(1) && imu.read();
        uint8_t reads_ok = (sonar_ok ? 1 : 0) + (imu_ok ? 1 : 0);

        if (sensors.isReady(0)) {
            sonar_fail_streak = sonar_ok ? 0 : sonar_fail_streak + 1;
            if (sonar_fail_streak >= SENSOR_FAULT_THRESHOLD)
                enterRelayOnlyMode("sonar read fault streak");
        }
        if (sensors.isReady(1)) {
            imu_fail_streak = imu_ok ? 0 : imu_fail_streak + 1;
            if (imu_fail_streak >= SENSOR_FAULT_THRESHOLD)
                enterRelayOnlyMode("imu read fault streak");
        }

        printSensorCsv(sonar_ok, imu_ok);

        static uint32_t last_sensor_log = 0;
        if (millis() - last_sensor_log >= 3000)
        {
            if (sensors.isReady(1))
            {
                Serial.printf("[SENSOR] reads ok=%d/%d | sonar=%.1f cm | accel=%.2f m/s2\n",
                              reads_ok, sensors.readyCount(), sonar.getValue(), imu.getValue());
            }
            else
            {
                Serial.printf("[SENSOR] reads ok=%d/%d | sonar=%.1f cm | accel=N/A (IMU not detected)\n",
                              reads_ok, sensors.readyCount(), sonar.getValue());
            }
            last_sensor_log = millis();
        }

        static uint32_t last_lora_raw = 0;
        if (lora_ok && millis() - last_lora_raw >= LORA_RAW_PUBLISH_INTERVAL_MS)
        {
            sensors.publishRaw(pubsub);
            last_lora_raw = millis();
        }
        last_sensor = millis();
    }

    if (!lora_ok)
        return; // 아래는 LoRa 필요 구간

#if DEMO_HEARTBEAT_ENABLED
    // 5초마다 하트비트 (QoS 0). 강등 시 status 바이트에 표시.
    static uint32_t last_hb = 0;
    if (millis() - last_hb > 5000)
    {
        uint8_t status = relay_only_mode ? HB_STATUS_DEGRADED : 0x00;
        uint8_t payload[2] = {75, status};
        pubsub.publish(TOPIC_HEARTBEAT, payload, 2);
        Serial.printf("[PUB] Heartbeat%s\n", relay_only_mode ? " (degraded)" : "");
        last_hb = millis();
    }
#endif

#if DEMO_ALERT_ENABLED
    // 10초마다 경보 (QoS 1). 강등 모드에서는 자체 alert 발행 금지.
    static uint32_t last_alert = 0;
    if (!relay_only_mode && millis() - last_alert > 10000)
    {
        uint8_t payload[1] = {90};
        bool enqueued = pubsub.publish(TOPIC_ALERT, payload, 1, true);
        Serial.printf("[PUB] ALERT -> %s\n", enqueued ? "enqueued" : "outbox full");
        last_alert = millis();
    }
#endif
}
