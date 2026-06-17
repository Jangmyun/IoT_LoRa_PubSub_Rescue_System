# LoRa Firmware

TTGO LoRa32 기반 부표 노드와 Raspberry Pi에 연결되는 LoRa 수신 게이트웨이 펌웨어입니다. PlatformIO 프로젝트로 구성되어 있으며, `lib/LoRaPubSub`에는 LoRa 위에서 동작하는 경량 pub/sub 프로토콜 구현이 들어 있습니다.

## 구성

| 경로 | 역할 |
| --- | --- |
| `src/main.cpp` | 부표 노드 펌웨어. 센서 샘플링, CSV 로그, heartbeat, raw publish 담당 |
| `src/gateway_main.cpp` | 게이트웨이 TTGO 펌웨어. LoRa 수신, CRC 검증, ACK 송신, Serial binary 출력 담당 |
| `lib/LoRaPubSub` | 패킷 포맷, publish, subscribe, relay, QoS-1 outbox, 중복 억제 |
| `lib/Sensors` | `SonarSensor`, `ImuSensor`, `SensorManager` |
| `test/test_loraPubSub` | native 환경에서 실행되는 LoRaPubSub 단위 테스트 |
| `diagram.json` | Wokwi 시뮬레이션 회로 |

## 하드웨어 기준

- MCU/LoRa: TTGO LoRa32 v2.1, ESP32 + SX1276
- LoRa 주파수: 923 MHz
- Sonar: AJ-SR04M, TRIG `GPIO13`, ECHO `GPIO12`
- IMU: MPU6050, SDA `GPIO21`, SCL `GPIO22`
- ECHO는 5 V 출력이므로 1 kΩ + 2.2 kΩ 분압 후 ESP32에 연결합니다.

## 프로토콜 요약

```text
[preamble | msg_type | node_id | msg_id | ttl | topic | pld_len | payload | crc8]
```

- 최대 크기: 11 bytes
- `LP_PREAMBLE`: `0xAB`
- `LP_MAX_PAYLOAD`: 3 bytes
- `LP_MAX_TTL`: 3
- `LP_OUTBOX_SIZE`: 4
- `LP_ACK_TIMEOUT_MS`: 800 ms

주요 topic:

| Topic | 값 | Payload |
| --- | ---: | --- |
| `TOPIC_ALERT` | `0x10` | confidence 1 byte |
| `TOPIC_ALERT_CLEAR` | `0x11` | 없음 |
| `TOPIC_HEARTBEAT` | `0x20` | battery 1 byte, status 1 byte |
| `TOPIC_SENSOR_RAW` | `0x21` | sonar 1 byte, accel 1 byte |
| `TOPIC_CMD_RESET` | `0x30` | 없음 |
| `TOPIC_CMD_CONFIG` | `0x31` | interval 1 byte, threshold 1 byte |

## 부표 펌웨어 빌드/업로드

업로드 전 `src/main.cpp`의 `NODE_ID`를 부표별로 바꿉니다.

```cpp
#define NODE_ID NODE_BUOY_A
```

```bash
cd LoRa_firmware
pio run -e ttgo-lora32-v21
pio run -e ttgo-lora32-v21 --target upload
pio device monitor -b 115200
```

Serial monitor에는 학습 데이터 수집용 CSV 로그가 출력됩니다.

```text
CSV,timestamp_ms,buoy_id,sonar_cm,accel_mag_ms2,sonar_valid,sonar_timeout,label
```

## 게이트웨이 펌웨어 업로드

Raspberry Pi에 USB Serial로 연결할 TTGO에는 `gateway` 환경을 업로드합니다.

```bash
cd LoRa_firmware
pio run -e gateway --target upload
```

게이트웨이 펌웨어는 LoRa 패킷을 검증한 뒤 다음 형식으로 Serial에 binary 출력합니다.

```text
LoRaPublish(11B) | rssi int16 little-endian(2B) | snr_x4 int8(1B)
```

이 출력은 `rpi-gateway-server/gateway/serial_reader.py`가 파싱합니다.

## 테스트

```bash
cd LoRa_firmware
pio test -e native
python -m pytest test/test_platformio_config.py
```

`native` 테스트는 실제 LoRa 하드웨어 없이 mock 기반으로 패킷 조립, CRC, relay, outbox 동작을 검증합니다.
