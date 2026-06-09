#pragma once
#include "ISensor.h"

// MPU-6050 가속도 센서. Adafruit MPU6050 라이브러리 사용.
// accel magnitude(m/s²)를 측정하여 수면 교란 여부 판정에 사용.
class ImuSensor : public ISensor {
public:
    bool    begin()     override;   // false = 센서 미발견
    bool    read()      override;
    float   getValue()  override { return _accel_mag; }
    uint8_t getPacked() override;   // accel_mag × 10 → 0–255 (0.0–25.5 m/s²)

private:
    float _accel_mag = 0;
};
