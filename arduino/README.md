# AIBI Arduino face detector

The active sketch is `AibiFaceDetector/AibiFaceDetector.ino`. Dependencies:
Arduino ESP32 Core **3.0.7**, LovyanGFX **1.3.0**, `esp_camera`, and the core's
bundled pretrained **HumanFaceDetectMSR01 + HumanFaceDetectMNP01** models.
No separate ESP-IDF project or Edge Impulse library is required.

The sketch now also includes the owner-tested **Hey Deskter** phoneme wake gate
and a Xiaozhi voice client. See [voice setup, dependencies and status](VOICE.md)
before uploading: the speech model needs the sketch's custom 8 MB partition
table and a separate model-image upload, which `build.ps1 -Upload` handles.

## Board, build and upload

Use XIAO ESP32S3, 8 MB flash, OPI PSRAM, Hardware CDC and JTAG, USB CDC On Boot
enabled, Default 8 MB partition scheme, and serial 115200. CPU is set to 240 MHz
in setup. The project retains existing camera/TFT wiring, ST7789 rotation 1,
320 x 240 RGB565 preview, 40 MHz SPI and panel inversion off. Sensor measured:
OV3660 (PID 0x3660). SD CS21 stays inactive. The onboard PDM microphone uses
GPIO42/41; speaker output uses GPIO43/44/6. Wi-Fi credentials are provisioned into
device NVS, independently of the sketch; passwords are not logged.

Arduino CLI 1.6.0 is installed at
`%LOCALAPPDATA%\Programs\ArduinoCLI\arduino-cli.exe`.

```powershell
cd D:\Projects\AIBI
.\arduino\build.ps1
.\arduino\build.ps1 -Upload -Port COM3
```

The script selects the board options explicitly and uploads through the ROM
loader. See [hardware](../HARDWARE.md) and [rollback archive locations](../CLEANUP.md).

## Two-core operation and memory ownership

The detector task is pinned to **core 0**. The installed Arduino configuration
sets `CONFIG_ARDUINO_RUNNING_CORE=1`, so the preview/display loop runs on **core 1**.
This does not measure per-core utilization or reserve an entire core for either
function. While asleep, the audio front end and phoneme model share core 0;
face inference starts after wake-up. The voice/network task shares core 1 with
the display. Both cores share PSRAM and memory bandwidth; camera/SPI drivers also
use interrupts and DMA.

Camera RGB565 buffers live in PSRAM. A single 150 KiB snapshot is copied for
inference. Its dimensions alternate between 320 x 240 and 240 x 320 according to
the requested quarter-turn; the pixel count and allocation size stay unchanged.
A queue token prevents overwriting the snapshot while inference owns it. Only
one job is in flight, so inference cannot build a backlog of old frames. Display
DMA finishes before returning its camera buffer. Camera initialization uses two
buffers, with a single-buffer fallback.

## Rotation, tilt and flipped images

The earlier build forced a 90-degree rotation and only searched +/-35 degrees
around it. That failed when the camera/robot was turned to other orientations.

The current build searches all four clockwise quarter-turns, each with 0 or
+/-35 degrees of tilt and an optional model-space horizontal reflection: 24
variants, covering horizontal/vertical image flips as well as upside-down input.
After a miss it tries nearby tilts and then other orientations. An angle that
returns a valid face is retained. Each job runs one real detector pass, rather
than running every angle on the same frame. Sudden rotations can therefore need
several seconds to reacquire. Multiple differently oriented faces are not searched
simultaneously.

Pixel copies and detection box corners use the same inverse transform. Startup
checks verify all 24 transforms/search coverage and compare actual copied camera
pixels against box mappings for all eight quarter-turn/reflection combinations.
These checks do not generate test detections or preview boxes. Tilted copies use
fixed-point pixel increments; out-of-frame areas are black, so coverage near the
edges can be reduced. Axis-aligned boxes around tilted faces can be larger.

The owner confirmed that green boxes reappear upright, sideways and upside-down.
See [validation](VALIDATION.md). A true side-profile view is a separate model
accuracy issue; the earlier upright photo was not sufficient evidence to blame
profile limitations before fixing orientation.

## Real results and tuning

Only real model results produce green boxes and model confidence labels. Empty
results clear boxes; capture ages above 600 ms are hidden. There is no fabricated
box persistence or predicted motion. The preview stays full-screen and is not
rotated or mirrored by the inference search.

`Settings.hpp` defaults: 240 MHz, 80 ms minimum snapshot interval, MSR top 10,
MNP top 5, resize scale 0.50, proposal threshold 0.10, visible face threshold 0.50.
MNP's internal diagnostic threshold is 0.05 so weaker scores can be logged;
results below 0.50 never draw boxes or retain an orientation. The earlier
160 MHz/three-proposal settings were rejected after reports of lag, misses and
restarts. No smaller/newer model or measured power saving is claimed.

## Diagnostics

Close other serial monitors before running either command:

```powershell
arduino-cli monitor --port COM3 --config baudrate=115200
python arduino/tools/monitor.py --port COM3 --seconds 55 --output arduino/runtime.log
```

`LIVE` reports uptime, FPS, camera errors, candidates, inference and preprocessing
time, quarter-turn (`turn`), tilt (`roll`), reflection (`mirror`), face scores and
boxes. `best` is the highest returned refinement score, or zero if none passed
the internal 0.05 threshold. `MEMORY` reports heap, PSRAM and stack headroom.
`BOOT` reports reset reason; opening a monitor can itself reset the board.

`THERMAL` reports the internal chip sensor (configured 20..100 C), actual CPU
frequency, inference rate and NN wall-time fraction. Temperature is an internal
trend reading, not case/ambient temperature. NN time fraction is not total CPU
utilization or electrical power. Snapshot-export and reference-image inference
paths have been removed from the active code.

## Cleanup

From the root, `./cleanup.ps1 -WhatIf` previews removal and `./cleanup.ps1`
removes obsolete ESP-IDF artifacts, build cache, old image diagnostics and logs.
Active sources and verified rollback ZIPs are retained. Automatic approval review
blocked agent deletion, so obsolete folders remain until cleanup is run locally.

## Primary references

- [Arduino Core 3.0.7 two-stage camera example](https://github.com/espressif/arduino-esp32/blob/3.0.7/libraries/ESP32/examples/Camera/CameraWebServer/app_httpd.cpp)
- [Espressif legacy detector tradeoffs](https://components.espressif.com/components/espressif/esp-dl/versions/1.1.0/examples/human_face_detect?language=en)
- [ESP32-S3 internal temperature sensor](https://docs.espressif.com/projects/esp-idf/en/v5.1.4/esp32s3/api-reference/peripherals/temp_sensor.html)
