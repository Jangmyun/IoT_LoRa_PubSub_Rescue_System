#pragma once
#include "Adafruit_Sensor.h"

class Adafruit_MPU6050 {
public:
    bool begin() { return false; }

    void getEvent(sensors_event_t* accel, sensors_event_t*, sensors_event_t*) {
        accel->acceleration.x = 0.0f;
        accel->acceleration.y = 0.0f;
        accel->acceleration.z = 0.0f;
    }
};
