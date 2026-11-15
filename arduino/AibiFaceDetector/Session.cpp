#include <Arduino.h>
#include <atomic>
#include <algorithm>
#include <cstring>
#include "freertos/semphr.h"
#include "Session.hpp"
#include "Settings.hpp"

namespace {
std::atomic<uint32_t> deadline{0}, wakes{0};
std::atomic<bool> enabled{false};
portMUX_TYPE statusLock = portMUX_INITIALIZER_UNLOCKED;
char status[96] = "Say Hey Deskter";
SemaphoreHandle_t heavyWork = nullptr;
}
namespace session {
bool begin() { heavyWork=xSemaphoreCreateMutex(); return heavyWork != nullptr; }
HeavyWork::HeavyWork() { xSemaphoreTake(heavyWork,portMAX_DELAY); }
HeavyWork::~HeavyWork() { xSemaphoreGive(heavyWork); }
void touch() { deadline.store(millis()+settings::awakeMs); }
void wake(float score) {
    touch(); enabled.store(true); wakes.fetch_add(1);
    Serial.printf("WAKE real phoneme match: Hey Deskter score=%.3f count=%lu\n", double(score), (unsigned long)wakes.load());
}
void sleep() { enabled.store(false); }
bool active() { return enabled.load() && int32_t(deadline.load()-millis()) > 0; }
uint32_t wakeCount() { return wakes.load(); }
void setStatus(const char *text) {
    char updated[sizeof(status)]{};
    snprintf(updated,sizeof(updated),"%s",text ? text : "");
    portENTER_CRITICAL(&statusLock);
    memcpy(status,updated,sizeof(status));
    portEXIT_CRITICAL(&statusLock);
}
void getStatus(char *out,unsigned capacity) {
    if (!capacity) return;
    portENTER_CRITICAL(&statusLock);
    const unsigned count = std::min<unsigned>(capacity-1,sizeof(status)-1);
    memcpy(out,status,count); out[count]=0;
    portEXIT_CRITICAL(&statusLock);
}
}
