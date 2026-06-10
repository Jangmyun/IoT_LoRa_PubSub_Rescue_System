#pragma once
#include "ISensor.h"

// HC-SR04 초음파 센서. 외부 라이브러리 없음, pulseIn() 직접 사용.
class SonarSensor : public ISensor {
public:
    SonarSensor(uint8_t trig, uint8_t echo);

    bool    begin()     override;
    bool    read()      override;   // false = 타임아웃(30ms 초과)
    float   getValue()  override { return _distance_cm; }
    uint8_t getPacked() override;   // 0–255 cm 클램프

private:
    uint8_t _trig;
    uint8_t _echo;
    float   _distance_cm = 0;
};
