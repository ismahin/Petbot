#pragma once
namespace voice {
bool begin();
void pollSerial();
unsigned stackFree();
float speakerLevel();
}
