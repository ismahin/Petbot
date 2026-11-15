#pragma once
#include <cstddef>
#include <cstdint>

namespace settings {
constexpr int width = 320, height = 240;
constexpr size_t frameBytes = width * height * 2;
constexpr int tftSck = 7, tftMosi = 9, tftCs = 1, tftDc = 2, tftReset = 4;
constexpr int sdCs = 21;
constexpr int micClock = 42, micData = 41;
constexpr uint32_t awakeMs = 60000;
constexpr float wakeThreshold = 0.70f;
constexpr int spiHz = 40000000;
constexpr bool panelInvert = false; // Confirmed correct on this owner's panel.
constexpr bool panelRgbOrder = false;
constexpr bool cameraMirror = false, cameraFlip = false;
constexpr uint32_t cpuMHz = 240; // Restore owner-confirmed responsive configuration.
constexpr uint32_t inferenceIntervalMs = 80;
constexpr uint32_t maxResultAgeMs = 600;
constexpr int proposalLimit = 10; // Avoid dropping a face behind background proposals.
constexpr int refinedFaceLimit = 5;
constexpr float proposalThreshold = 0.10f; // Espressif Arduino two-stage example.
constexpr float faceThreshold = 0.50f;
constexpr float refinementProbeThreshold = 0.05f; // Log weaker results; never draw below faceThreshold.
constexpr float detectorScale = 0.50f; // QVGA: keep enough detail for smaller faces.
// Index = mirrored*12 + clockwiseQuarterTurns*3 + tiltIndex.
// Portrait and landscape jobs have identical pixel counts: one 150 KiB snapshot.
constexpr int rollAngles[] = {0, 35, -35};
constexpr unsigned rollAngleCount = sizeof(rollAngles) / sizeof(rollAngles[0]);
constexpr unsigned poseCount = 2*4*rollAngleCount;
static_assert(poseCount <= 32, "Orientation search uses a 32-bit tried mask");
constexpr uint8_t poseSearchOrder[] = {
    0, 3, 6, 9, 1, 2, 4, 5, 7, 8, 10, 11,
    12, 15, 18, 21, 13, 14, 16, 17, 19, 20, 22, 23
};
static_assert(sizeof(poseSearchOrder) == poseCount, "Search must cover all poses");
constexpr unsigned maxFaces = 8;
}
