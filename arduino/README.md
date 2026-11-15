# Deskter animated Arduino companion

The active sketch is `AibiFaceDetector/AibiFaceDetector.ino` (the existing folder
name is retained for build/upload compatibility). It now displays animated robot
eyes, with **camera capture and face detection off by default**.
Camera wiring is unchanged. Say **Hey Deskter, open camera** to open a full-screen
320x240 preview with real face detection. Say **close camera** (or wake Deskter
first if needed) to return to the animated eyes.

## Behavior

- Soft cyan eyes: eased gaze, natural blinks and idle breathing.
- Listening: attentive eyes and a pulsing indicator.
- Thinking/connecting: moving dots and an upward gaze.
- Speaking: mouth bars follow the RMS of decoded audio; silent gaps settle down.
- Boot: a short four-note chime on the existing I2S speaker.
- Offline: a captive Wi-Fi portal with asynchronous SSID scanning, manual hidden
  network entry and password submission. Credentials stay in device NVS.
- Real **Hey Deskter** phoneme wake detection starts a cloud voice session.
- Open/close camera commands have local phoneme matches, including a four-second
  command window after the wake phrase, plus a strict cloud-transcription command
  path during conversation. Ordinary questions about cameras do not toggle it.
- Camera mode uses the previously working pretrained HumanFaceDetectMSR01 +
  HumanFaceDetectMNP01 models, original Sense pinout, RGB565 and 24-pose orientation
  search. Only real results above threshold draw green boxes and confidence.
  Closing waits for inference to finish, deinitializes the camera and releases
  model/snapshot/queue storage. It stays off on the next boot.
  The mic is suppressed during speaker playback (half-duplex; no echo cancellation).
- A session returns to wake-word standby after 60 seconds without activity.
  Server preparation heartbeats and real audio extend the session.

The display uses a 150 KiB PSRAM sprite and targets 30 FPS without blocking the
network or microphone tasks. Actual frame rate is printed as `EYES fps`.
Eye SPI updates are clipped to the animated area between full refreshes. Camera
buffers and face-model scratch memory are allocated only while camera mode is open.
While asleep in camera mode, local command detection shares core 0 with face
inference; reacquisition/performance can differ from the earlier camera-only build.

## Hardware and dependencies

XIAO ESP32S3 Sense, Arduino ESP32 Core **3.0.7**, OPI PSRAM, 8 MB flash,
LovyanGFX **1.3.0**, ArduinoJson **7.4.3**, WebSockets **2.7.2**, esp32_opus
**1.0.3**, plus the core's I2S/Wi-Fi/Preferences/ESP-SR libraries.

ST7789 landscape 320x240: SCK7, MOSI9, CS1, DC2, RESET4, 40 MHz, inversion off.
Sense PDM microphone CLK42/DATA41; amplifier BCLK43/WS44/DIN6. SD CS21 stays high.
No GPIO wiring changes are needed. USB power is recommended for development.

The local wake gate uses the bundled pretrained MultiNet5 Q8 English model with
custom phoneme strings for Hey Deskter / Hey Dexter. Its model image and custom
8 MB flash partition table are still required. No cloud API key is compiled
into the firmware; each board's device key is provisioned into NVS over USB.

## Build, upload and provision

```powershell
cd D:\Projects\AIBI
.\arduino\build.ps1
.\arduino\build.ps1 -Upload -Port COM3
server/.venv/Scripts/python.exe arduino/tools/provision_cloud.py --port COM3
```

The upload script uses Arduino CLI at
`%LOCALAPPDATA%\Programs\ArduinoCLI\arduino-cli.exe`, explicitly selects
XIAO ESP32S3/OPI PSRAM, and flashes both the bundled speech model and application.
It preserves NVS Wi-Fi settings, UUID and server configuration. There is no
second application slot for firmware OTA.

Cloud provisioning first verifies real HTTPS health, device-key authentication
and the selected secure WebSocket URL. By default it reads the ignored
`cloud/private/vercel.env` and selects `https://robotpetbot.vercel.app`.
The board then uses its trusted public CA bundle and public SNTP clock.
Do not put API keys, Wi-Fi passwords or private env files in Git.

The existing serial LAN-server configuration remains supported with its pinned
CA and LAN clock; see [historical voice integration notes](VOICE.md).

## Wi-Fi setup

If saved Wi-Fi does not connect in about 25 seconds, or no network is saved:

1. Join **Deskter Setup**, password **deskter123** on your phone.
2. Open the captive setup page. If it does not open automatically, visit
   **http://192.168.4.1/**. OS automatic portal behavior varies.
3. Select a scanned 2.4 GHz SSID (or type a hidden SSID), enter its password and
   tap Connect Deskter. Open networks allow an empty password.
4. The robot saves the credentials, joins Wi-Fi, closes its hotspot and contacts
   the selected cloud server. A failed connection keeps setup available and retries.
5. Say **Hey Deskter**, wait for the listening animation, then ask your question.

There is no Xiaozhi account activation code for this private server. Device
access uses the configured device API key. The cloud Studio needs Redis to save
settings and manage individual device keys; the bootstrap device key works
without Redis. Vercel cold starts can delay the first reply.

## Diagnostics and limitations

```powershell
python arduino/tools/monitor.py --port COM3 --seconds 55 --output arduino/eyes_runtime.log
```

`EYES`: FPS, state enum, internal/PSRAM headroom. Visual states are Boot0, Idle1,
Connecting2, Setup3, Listening4, Thinking5, Speaking6, Error7. `VOICE` reports
Wi-Fi, HTTPS configuration, WebSocket hello and audio counters. `PLAYBACK`
reports queue drops/underruns. `AUDIO` reports actual wake-model detections and
mic-read errors. Logs do not contain passwords or device keys.

Emotion-controlled TTS quality and response latency remain properties of the
server/model. Speaking animation follows real playback, not generated text or
fake audio. The owner confirmed the listening/thinking/speaking animations, boot chime,
spoken open/close camera commands and visible green face box on 2026-11-16.

## Validation on 2026-11-16

- Final Arduino build and COM3 flash passed; application hash verified by esptool.
  Image: 2,515,536 bytes, SHA256
  `4f7cb8199292109265db897494f6012d83dee79a5a92e5177dcf481a6e320b25`.
- Board authenticated to `robotpetbot.vercel.app` using the provisioned device
  key. Public HTTPS configuration, authenticated WSS/Opus hello and real Mithi
  WAV synthesis passed. Cloud API checks (14 tests) and Vercel deployment passed.
- Eyes measured 29.2..29.6 FPS; camera measured about 10.3..11.1 FPS with local
  phoneme recognition sharing core 0. Camera capture error count stayed zero.
- Two real camera open/close cycles restored exactly 162,924 bytes free internal
  heap and 5,741,072 bytes free PSRAM after each close. No MCU panic was captured.
  Minimum internal heap reached 18,456 bytes during this short camera test;
  this is not a long-run stability or power measurement. The core's camera
  teardown emitted a GDMA disconnect warning; the second open and close worked.
- On the actual board, the portal served its HTML, scanned 30 visible networks,
  rejected invalid credentials, redirected captive probes and answered wildcard
  DNS with 192.168.4.1. Phone auto-opening remains dependent on its OS.
- The owner confirmed real spoken commands open the preview, show a green face
  box, and close back to eyes; all action animations and the boot sound work.

Ignored captures: `companion_build_final.log`, `companion_upload.log`,
`companion_check.log`, `companion_runtime.log`. A trusted USB diagnostic can
send `{"cmd":"setup","enabled":true}` to reopen setup for five minutes while
Wi-Fi is connected; `enabled:false` closes it. `{"cmd":"info"}` reports the
board's LAN IP, and `{"cmd":"camera","enabled":true}` controls camera mode for
hardware diagnostics. None of these commands generate artificial detections.
