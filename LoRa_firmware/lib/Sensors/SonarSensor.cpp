#include "SonarSensor.h"
#include <Arduino.h>

static constexpr uint32_t SONAR_TIMEOUT_US = 30000; // 30ms → 약 5m 최대 측정 거리

SonarSensor::SonarSensor(uint8_t trig, uint8_t echo)
    : _trig(trig), _echo(echo) {}

bool SonarSensor::begin() {
    pinMode(_trig, OUTPUT);
    pinMode(_echo, INPUT);
    digitalWrite(_trig, LOW);
    return true;
}

bool SonarSensor::read() {
    // 10µs TRIG 펄스 송출
    digitalWrite(_trig, LOW);
    delayMicroseconds(2);
    digitalWrite(_trig, HIGH);
    delayMicroseconds(10);
    digitalWrite(_trig, LOW);

    // ECHO 폭 측정
    uint32_t duration = pulseIn(_echo, HIGH, SONAR_TIMEOUT_US);
    if (duration == 0) return false;

    _distance_cm = duration / 58.0f;
    return true;
}

uint8_t SonarSensor::getPacked() {
    if (_distance_cm > 255.0f) return 255;
    return static_cast<uint8_t>(_distance_cm);
}
