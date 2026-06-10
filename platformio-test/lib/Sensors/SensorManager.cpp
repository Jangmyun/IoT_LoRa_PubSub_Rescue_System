#include "SensorManager.h"

void SensorManager::attach(ISensor* s) {
    if (!s || _count >= MAX_SENSORS) return;
    _sensors[_count] = s;
    _ready[_count] = false;
    _count++;
}

uint8_t SensorManager::beginAll() {
    uint8_t ready = 0;
    for (uint8_t i = 0; i < _count; i++) {
        _ready[i] = _sensors[i]->begin();
        if (_ready[i]) ready++;
    }
    return ready;
}

uint8_t SensorManager::readAll() {
    uint8_t read_ok = 0;
    for (uint8_t i = 0; i < _count; i++) {
        if (!_ready[i]) continue;
        if (_sensors[i]->read()) read_ok++;
    }
    return read_ok;
}

void SensorManager::publishRaw(LoRaPubSub& pubsub) {
    if (_count == 0) return;

    uint8_t payload[MAX_SENSORS];
    uint8_t payload_len = 0;
    for (uint8_t i = 0; i < _count; i++) {
        if (!_ready[i]) continue;
        payload[payload_len++] = _sensors[i]->getPacked();
    }
    if (payload_len == 0) return;

    pubsub.publish(TOPIC_SENSOR_RAW, payload, payload_len);
}

uint8_t SensorManager::readyCount() const {
    uint8_t ready = 0;
    for (uint8_t i = 0; i < _count; i++) {
        if (_ready[i]) ready++;
    }
    return ready;
}

bool SensorManager::isReady(uint8_t index) const {
    if (index >= _count) return false;
    return _ready[index];
}
