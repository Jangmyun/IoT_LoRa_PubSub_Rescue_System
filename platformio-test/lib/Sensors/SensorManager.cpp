#include "SensorManager.h"

void SensorManager::attach(ISensor* s) {
    if (!s || _count >= MAX_SENSORS) return;
    _sensors[_count++] = s;
}

void SensorManager::beginAll() {
    for (uint8_t i = 0; i < _count; i++)
        _sensors[i]->begin();
}

void SensorManager::readAll() {
    for (uint8_t i = 0; i < _count; i++)
        _sensors[i]->read();
}

void SensorManager::publishRaw(LoRaPubSub& pubsub) {
    if (_count == 0) return;

    uint8_t payload[MAX_SENSORS];
    for (uint8_t i = 0; i < _count; i++)
        payload[i] = _sensors[i]->getPacked();

    pubsub.publish(TOPIC_SENSOR_RAW, payload, _count);
}
