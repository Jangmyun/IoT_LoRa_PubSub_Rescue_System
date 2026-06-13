#include "ImuSensor.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <math.h>

static Adafruit_MPU6050 _mpu;

bool ImuSensor::begin() {
    // AD0 핀 LOW=0x68(기본), HIGH=0x69 — 모듈에 따라 다르므로 둘 다 시도
    if (_mpu.begin(0x68)) return true;
    return _mpu.begin(0x69);
}

bool ImuSensor::read() {
    sensors_event_t a, g, temp;
    _mpu.getEvent(&a, &g, &temp);
    _accel_mag = sqrtf(a.acceleration.x * a.acceleration.x +
                       a.acceleration.y * a.acceleration.y +
                       a.acceleration.z * a.acceleration.z);
    return true;
}

uint8_t ImuSensor::getPacked() {
    float scaled = _accel_mag * 10.0f;
    if (scaled > 255.0f) return 255;
    return static_cast<uint8_t>(scaled);
}
