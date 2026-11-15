#pragma once
#include <cstddef>
#include <cstdint>

namespace wakeaudio {
bool begin();
size_t readPcm(void *destination, size_t maximumBytes);
void discardPcm();
void setSpeaking(bool value);
bool speaking();
}
