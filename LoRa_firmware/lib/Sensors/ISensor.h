#pragma once
#include <stdint.h>

class ISensor {
public:
    virtual bool    begin()     = 0;  // 초기화, 성공 여부 반환
    virtual bool    read()      = 0;  // 하드웨어 읽기, 성공 여부 반환
    virtual float   getValue()  = 0;  // 마지막 읽은 값 (cm 또는 m/s²)
    virtual uint8_t getPacked() = 0;  // 1바이트 양자화 값 (LoRa payload용)
    virtual ~ISensor() = default;
};
