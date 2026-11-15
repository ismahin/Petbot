#pragma once
class PetDisplay;
namespace cameramode {
void request(bool enabled);
bool requested();
bool render(PetDisplay &lcd);
}
