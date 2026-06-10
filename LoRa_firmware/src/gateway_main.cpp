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

static uint8_t _crc8_gw(const uint8_t* data, uint8_t len) {
    uint8_t crc = 0x00;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++)
            crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
    }
    return crc;
}

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

    // raw 바이트를 직접 읽어 가변 길이 CRC 위치를 정확히 처리
    uint8_t raw[sizeof(LoRaPublish)] = {};
    int raw_len = 0;
    while (LoRa.available() && raw_len < (int)sizeof(raw))
        raw[raw_len++] = (uint8_t)LoRa.read();
    while (LoRa.available()) LoRa.read();  // 초과 바이트 드레인

    if (raw[0] != LP_PREAMBLE) return;
    if (raw[1] != MSG_PUBLISH && raw[1] != MSG_RELAY) return;

    uint8_t pld_len = raw[sizeof(LoRaHeader) + 1];
    if (pld_len > LP_MAX_PAYLOAD) return;

    uint8_t crc_offset = sizeof(LoRaHeader) + 2 + pld_len;
    if (raw_len < (int)(crc_offset + 1)) return;

    // 펌웨어에서 CRC 검증 — 깨진 패킷을 사전에 걸러냄
    if (_crc8_gw(raw, crc_offset) != raw[crc_offset]) return;

    // 가변 길이 raw → 정규화된 LoRaPublish 구조체로 변환
    LoRaPublish pkt{};
    memcpy(&pkt.header, raw, sizeof(LoRaHeader));
    pkt.topic   = raw[sizeof(LoRaHeader)];
    pkt.pld_len = pld_len;
    memcpy(pkt.payload, raw + sizeof(LoRaHeader) + 2, pld_len);
    pkt.crc8    = raw[crc_offset];

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
