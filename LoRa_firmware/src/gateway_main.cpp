#include <Arduino.h>
#include <SPI.h>
#include <LoRa.h>
#include "LoRaPubSub.h"   // 패킷 구조체·상수만 사용

// TTGO LoRa32 핀 정의
#define LORA_SCK   5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_SS    18
#define LORA_RST   14
#define LORA_DI0   26

// LoRa 설정 (부표 노드와 반드시 일치)
#define LORA_FREQ    923E6
#define LORA_SF      7
#define LORA_BW      125E3
#define LORA_SYNC    0xAB

void setup() {
    Serial.begin(115200);

    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DI0);

    if (!LoRa.begin(LORA_FREQ)) {
        // 초기화 실패 — 무한 대기 (Serial 출력 없음, 순수 바이너리 모드 유지)
        while (true) delay(1000);
    }

    LoRa.setSpreadingFactor(LORA_SF);
    LoRa.setSignalBandwidth(LORA_BW);
    LoRa.setSyncWord(LORA_SYNC);
    LoRa.receive();
}

void loop() {
    int size = LoRa.parsePacket();
    // 최소 패킷: header(5) + topic(1) + pld_len(1) + crc8(1) = 8 바이트
    if (size < (int)(sizeof(LoRaHeader) + 3)) return;

    LoRaPublish pkt{};
    LoRa.readBytes(reinterpret_cast<uint8_t*>(&pkt),
                   min((int)sizeof(LoRaPublish), size));

    if (pkt.header.preamble != LP_PREAMBLE) return;

    // ── 순수 바이너리 출력 ─────────────────────────────────────────
    // 포맷: LoRaPublish(11B) | rssi int16 LE(2B) | snr_x4 int8(1B)
    // RPI serial_reader.py 가 이 포맷을 파싱한다.
    Serial.write(reinterpret_cast<const uint8_t*>(&pkt), sizeof(LoRaPublish));
    int16_t rssi   = (int16_t)LoRa.packetRssi();
    int8_t  snr_x4 = (int8_t)(LoRa.packetSnr() * 4.0f);
    Serial.write(reinterpret_cast<uint8_t*>(&rssi),   sizeof(rssi));
    Serial.write(reinterpret_cast<uint8_t*>(&snr_x4), sizeof(snr_x4));
    Serial.flush();
}
