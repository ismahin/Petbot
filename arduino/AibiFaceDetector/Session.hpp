#pragma once
#include <cstdint>

namespace session {
enum class Visual : uint8_t { Boot, Idle, Connecting, Setup, Listening, Thinking, Speaking, Error };
void setVisual(Visual value);
Visual visual();
bool begin();
class HeavyWork {
public:
    HeavyWork();
    ~HeavyWork();
    HeavyWork(const HeavyWork &) = delete;
    HeavyWork &operator=(const HeavyWork &) = delete;
};
void wake(float score);
void touch();
void sleep();
bool active();
uint32_t wakeCount();
void setStatus(const char *text);
void getStatus(char *out, unsigned capacity);
}
