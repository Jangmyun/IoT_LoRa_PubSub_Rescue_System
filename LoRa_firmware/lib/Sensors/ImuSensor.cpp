#include "ImuSensor.h"
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <math.h>

static Adafruit_MPU6050 _mpu;

bool ImuSensor::begin() {
    // I2C 버스가 전원 인가 직후 아직 안정화되지 않을 수 있으므로
    // 100ms 간격으로 최대 3회 재시도한다.
    for (uint8_t attempt = 0; attempt < 3; attempt++) {
        if (attempt > 0) delay(100);
        if (_mpu.begin(0x68)) return true;
        if (_mpu.begin(0x69)) return true;
    }
    return false;
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
