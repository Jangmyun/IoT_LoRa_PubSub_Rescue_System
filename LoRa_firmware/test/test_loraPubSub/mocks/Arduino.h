#pragma once
#include <stdint.h>
#include <string.h>
#include <algorithm>

extern uint32_t _mock_millis;
inline uint32_t millis() { return _mock_millis; }

static constexpr int INPUT = 0;
static constexpr int OUTPUT = 1;
static constexpr int LOW = 0;
static constexpr int HIGH = 1;

inline void pinMode(uint8_t, int) {}
inline void digitalWrite(uint8_t, int) {}
inline void delayMicroseconds(uint32_t) {}
inline uint32_t pulseIn(uint8_t, int, uint32_t) { return 0; }

using std::min;
