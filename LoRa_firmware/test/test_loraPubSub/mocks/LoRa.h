#pragma once
#include <stdint.h>
#include <string.h>

extern uint32_t _mock_millis;

// LoRa TX/RX spy. parsePacket advances _mock_millis by 100ms per call so
// the QoS-1 ACK timeout loop (800ms window) terminates without real waiting.
struct MockLoRa {
    // TX spy
    uint8_t tx_buf[256];
    int     tx_len;

    // RX packet queue
    struct Pkt { uint8_t buf[256]; int size; };
    Pkt rx_q[8];
    int rx_head, rx_tail;

    MockLoRa() : tx_len(0), rx_head(0), rx_tail(0) {}

    void reset() {
        tx_len   = 0;
        rx_head  = rx_tail = 0;
    }

    // Config stubs (no-op in tests)
    void setSyncWord(uint8_t /*sw*/)             {}
    void setSpreadingFactor(int /*sf*/)          {}
    void setSignalBandwidth(long /*bw*/)         {}

    // TX
    void   beginPacket()                         { tx_len = 0; }
    size_t write(const uint8_t *buf, size_t sz)  { memcpy(tx_buf + tx_len, buf, sz); tx_len += sz; return sz; }
    void   endPacket(bool /*async*/ = false)      {}
    void   receive()                              {}

    // RX — each call advances time so QoS-1 deadline eventually expires
    int parsePacket() {
        _mock_millis += 100;
        return (rx_head != rx_tail) ? rx_q[rx_head].size : 0;
    }

    int readBytes(uint8_t *buf, int len) {
        if (rx_head == rx_tail) return 0;
        memcpy(buf, rx_q[rx_head].buf, len);
        rx_head = (rx_head + 1) % 8;
        return len;
    }

    void injectRx(const uint8_t *data, int sz) {
        memcpy(rx_q[rx_tail].buf, data, sz);
        rx_q[rx_tail].size = sz;
        rx_tail = (rx_tail + 1) % 8;
    }
};

extern MockLoRa LoRa;
