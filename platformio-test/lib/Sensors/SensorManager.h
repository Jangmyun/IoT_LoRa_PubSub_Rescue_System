#pragma once
#include "ISensor.h"
#include "LoRaPubSub.h"

// ISensor 포인터 배열을 관리하고 LoRaPubSub으로 센서 데이터를 발행한다.
// attach()로 센서를 끼우고 빼는 유연한 구조를 지원한다.
class SensorManager {
public:
    static constexpr uint8_t MAX_SENSORS = 4;

    // 센서 등록. nullptr 및 슬롯 초과 시 무시.
    void attach(ISensor* s);

    // 등록된 모든 센서 begin() 호출.
    void beginAll();

    // 등록된 모든 센서 read() 호출.
    void readAll();

    // 등록 순서대로 getPacked() → TOPIC_SENSOR_RAW payload로 발행 (QoS 0).
    void publishRaw(LoRaPubSub& pubsub);

    uint8_t count() const { return _count; }

private:
    ISensor* _sensors[MAX_SENSORS] = {};
    uint8_t  _count = 0;
};
