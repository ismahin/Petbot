# Arduino validation - 2026-11-13

The face-only measurements below describe the owner-confirmed baseline before
wake/voice integration. See [voice status](VOICE.md) for the current combined
firmware; its memory use, flash layout and performance differ.

## Confirmed face-only baseline

Arduino CLI **1.6.0**, Arduino ESP32 Core **3.0.7**, LovyanGFX **1.3.0**.
FQBN: `esp32:esp32:XIAO_ESP32S3:PSRAM=opi,USBMode=hwcdc,CDCOnBoot=default,PartitionScheme=default_8MB,UploadSpeed=115200`.
Real pretrained MSR01 proposals and MNP01 refinement are bundled with the core.
No standalone ESP-IDF build, Edge Impulse model or placeholder detections are used.

- CPU 240 MHz; minimum inference interval 80 ms; proposal limit 10; refined limit 5.
- Detector resize scale 0.50; proposal threshold 0.10; visible face threshold 0.50.
- MNP diagnostic output threshold 0.05; weak results cannot draw boxes or retain orientation.
- Quarter-turns 0/90/180/270, each with 0/+35/-35 tilt and optional reflection.
- One pass per job; retain a successful orientation; search after misses.
- One 150 KiB PSRAM snapshot reused for both 320x240 and 240x320 inputs.
- Original camera/TFT GPIOs and 320x240 RGB565 preview unchanged; inversion off.
- Camera measured as OV3660 (PID 0x3660), 20 MHz XCLK, two frame buffers.

Compilation and upload passed, with esptool verification of written data.
Application binary: **1,134,848 bytes**; reported program usage **1,134,489 /
3,342,336 bytes** (33%). Static RAM **33,956 / 327,680 bytes** (10%).
Application SHA256:
`834ef2ebbe378a03b17186f492e9c6ad817bf27225f106f21d193f262114f4fe`.
Logs before manual cleanup: `orientation_build.log`, `orientation_upload.log`,
`orientation_runtime.log`.

## Confirmed rotation behavior

The previous +/-35 degree search was centered on a forced 90-degree rotation.
The owner's photo showed a nearly front-facing face without a box; a profile
limitation was not an adequate explanation for that orientation failure.

Startup checks passed for all 24 geometry transforms and search coverage.
A separate pixel check on an actual camera frame compared the fast copy path
with box-coordinate mapping at corners and interior points for all eight
quarter-turn/reflection combinations. Serial explicitly logged that check passed.
No artificial faces/boxes from these checks are displayed.

After the updated firmware was flashed, the owner confirmed:
**"Works in upright, sideways and upside-down positions."**
Earlier tests also confirmed normal display colors and improved head-tilt detection.
The serial log contains real positive detections using different quarter-turns,
including mirrored inference input. Detection scores above 0.99 were observed.
These are model scores, not a measured accuracy percentage.

## Runtime check

The 55-second capture showed increasing uptime from 4 through 55 seconds, no
captured panic/reset and zero reported camera errors. Preview was about
**10.9-11.2 FPS**. One-proposal inference was about **85 ms** and two-proposal
inference about **120 ms**. Observed preprocessing copies took about **11-14 ms**
for rotated/reflected input. Proposal count and scene affect timing.

Minimum free internal heap: **127,004 bytes**. Free stack minimum: **13,752 bytes**
for the loop, **13,904 bytes** for detection. Temperature trended around **47 C**
in the captured run. This is an internal chip reading, not case temperature or
an electrical power measurement; different scene/ambient conditions prevent
claiming a controlled temperature improvement.

## Core assignment verified from installed code/configuration

`App.cpp` pins the detection task to core **0** using `xTaskCreatePinnedToCore`.
The installed S3 qio_opi `sdkconfig.h` defines `CONFIG_ARDUINO_RUNNING_CORE 1`;
Core 3.0.7's `main.cpp` creates `loopTask` on `ARDUINO_RUNNING_CORE`. The preview
and display loop therefore runs on core **1**. Both cores share memory and
bandwidth; this configuration check is not a utilization measurement.

## Limits and earlier experiments

This is a short hardware check, not an extended reliability or pose-accuracy
benchmark. Large changes can take several seconds to reacquire because variants
are tested sequentially. Different face orientations are not searched in
parallel. Rotated tilt input loses some edge coverage and mapped axis-aligned
boxes can be larger. True side profiles remain a separate, unbenchmarked model
limitation; the rotation fix does not establish reliable profile support.

The 160 MHz/three-proposal experiments reduced temperatures in some short runs
but were rejected after reports of lag, misses and restarts. The reset cause
was not established. An earlier raw-snapshot export session also produced an
IllegalInstruction panic with an unconfirmed cause. Raw snapshot export and the
reference-image inference test are now removed from active code. Neither
watchdog nor brownout protection was disabled. `BOOT reset_reason`, `LIVE uptime`
and heap/stack/temperature logs support future diagnosis. Opening a serial
monitor can itself reset the board, and startup lines may be missed.

Wi-Fi/audio integration, battery operation, controlled no-face false-positive
tests and long-duration stability need further testing. No new model, improved
profile accuracy, fake detections or measured electrical power saving is claimed.

## Offline Bangla integration, 2026-11-14

The local-server Arduino build compiled and uploaded with flash hash verification.
The real XIAO obtained HTTPS configuration and synchronized its clock with the PC
over the LAN, then exchanged microphone/Opus audio with the local gateway. The
owner confirmed hearing Bangla replies. A short combined run showed approximately
9–11 FPS preview, no reported codec errors, minimum internal heap 15.8 KiB and
voice stack headroom 6152 bytes. Die temperature reached 63 C. Occasional camera
EV-VSYNC-OVF warnings remain; this short run is not a long-duration stability test.
Face accuracy was not re-benchmarked during the voice test. See server/README.md
for local models, latency measurements and remaining limitations.

## Cleanup and rollback

Verified rollback ZIPs are retained in `../backups`; the tilt-only pre-change
firmware is in `arduino_before_full_orientation.zip`. The original two archives
also had their binary hashes verified. Automatic approval review blocked agent
deletion with the reason "blocked by policy". Obsolete files remain until
`../cleanup.ps1` is run locally; the script preserves active sources and backups.
