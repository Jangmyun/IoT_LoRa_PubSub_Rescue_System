#pragma once
#include <stdint.h>
#include <string.h>
#include <algorithm>

extern uint32_t _mock_millis;
inline uint32_t millis() { return _mock_millis; }

using std::min;
