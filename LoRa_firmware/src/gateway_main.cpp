#include <Arduino.h>
#include <LoRa.h>
#include <SPI.h>
#include <string.h>
#include "LoRaPubSub.h"

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

static bool lora_ok = false;

static uint8_t crc8(const uint8_t* data, uint8_t len) {
    uint8_t crc = 0x00;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t j = 0; j < 8; j++) {
            crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
        }
    }
    return crc;
}

static bool normalizePublishPacket(const uint8_t* raw, int raw_len, LoRaPublish& pkt) {
    const uint8_t header_len = sizeof(LoRaHeader);
    const uint8_t min_publish_len = header_len + 2 + 1; // header + topic + pld_len + crc
    if (raw_len < min_publish_len) return false;
    if (raw[0] != LP_PREAMBLE) return false;
    if (raw[1] != MSG_PUBLISH && raw[1] != MSG_RELAY) return false;

    uint8_t pld_len = raw[header_len + 1];
    if (pld_len > LP_MAX_PAYLOAD) return false;

    uint8_t crc_offset = header_len + 2 + pld_len;
    if (raw_len < (int)(crc_offset + 1)) return false;

    uint8_t expected_crc = crc8(raw, crc_offset);
    if (expected_crc != raw[crc_offset]) return false;

    memset(&pkt, 0, sizeof(pkt));
    memcpy(&pkt.header, raw, header_len);
    pkt.topic = raw[header_len];
    pkt.pld_len = pld_len;
    memcpy(pkt.payload, raw + header_len + 2, pld_len);
    pkt.crc8 = raw[crc_offset];
    return true;
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_SS);
    LoRa.setPins(LORA_SS, LORA_RST, LORA_DI0);

    lora_ok = LoRa.begin(923E6);
    if (!lora_ok) {
        Serial.println("[GATEWAY] LoRa init failed");
        return;
    }

    LoRa.setSyncWord(0xAB);
    LoRa.receive();
    Serial.println("[GATEWAY] LoRa RX bridge ready");
}

void loop() {
    if (!lora_ok) return;

    int packet_size = LoRa.parsePacket();
    if (packet_size <= 0) return;

    uint8_t raw[sizeof(LoRaPublish)] = {};
    int raw_len = 0;
    while (LoRa.available() && raw_len < (int)sizeof(raw)) {
        raw[raw_len++] = (uint8_t)LoRa.read();
    }
    while (LoRa.available()) {
        LoRa.read();
    }

    LoRaPublish pkt{};
    if (normalizePublishPacket(raw, raw_len, pkt)) {
        Serial.write(reinterpret_cast<const uint8_t*>(&pkt), sizeof(pkt));
        Serial.flush();
    }

    LoRa.receive();
}
