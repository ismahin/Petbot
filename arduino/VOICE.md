# Deskter wake phrase and Xiaozhi voice

**Historical integration notes:** the active companion firmware now uses animated
eyes, a boot chime and scanned Wi-Fi setup, with camera/face detection disabled.
See [current Arduino instructions](README.md) for cloud provisioning and operation.
Face-preview measurements and official activation steps below describe earlier
firmware, rather than the current private-cloud workflow.

Status: the phoneme wake gate is uploaded and owner-tested. The combined Xiaozhi
network/speaker client compiles and its on-board Opus encode/decode self-check
passes. Wi-Fi settings are stored on the device. After the owner connected the
external antenna, the board joined Wi-Fi and obtained Xiaozhi cloud settings.
The corrected WebSocket handshake was accepted; real server transcription,
incoming Opus decoding and I2S writes have been observed without audio errors.
The owner confirmed spoken replies in the earlier build, which stayed in Chinese.
Activation is now fixed and server-confirmed: the client reads the real STA MAC
with esp_read_mac and formats it in lowercase, matching the official firmware.
The persistent client UUID and saved Wi-Fi settings are preserved. The service
issued a real six-digit code; activation polling changed from HTTP 202 to 200.
A subsequent configuration request omitted activation and supplied ready cloud
settings. No fabricated MAC, UUID reset, fake code or eFuse changes were used.
English conversation after account binding remains to be tested. The temporary
first-reply/code-capture diagnostic has been removed; the client now displays
only real activation data from the configuration service.

## Offline Bangla server (2026-11-14)

The current uploaded Arduino build additionally accepts a private HTTPS
configuration endpoint, pinned PEM CA, device token and LAN clock address via
USB, stored in NVS without printing credentials. Flash hash verification passed.
The board synchronized with the PC over UDP 8123, received authenticated HTTPS
configuration (200), connected by WSS and exchanged real microphone/Opus audio.
Local mode stops public SNTP. The PC performs all Bangla speech/LLM inference;
the face/wake models and GPIO assignments remain on the XIAO. Speaker digital
gain remains 100%. Official binding, UUID and Wi-Fi are preserved for rollback.
See [server instructions](../server/README.md) for current validation and limits.

## Wake phrase

The PC server uses Groq for conversation and Mithi v1 Edge / Malini for local
speech. Synthesis overlaps queued playback. Audio is 48 kbit/s with a four-frame
prefill. See [current server setup](../server/README.md).

Say **Hey Deskter** using the XIAO Sense onboard PDM mic (clock 42, data 41).
The real pretrained **MultiNet5 Q8 English** model bundled with Arduino ESP32
Core 3.0.7 acts as a custom phrase gate. This uses phoneme strings, not a retrained
WakeNet model. Both Desk-ter and Dexter pronunciations map to the same wake ID:
`hd DfSKTk` and `hd DfKSTk`, using Arduino's official G2P alphabet.

The 16 kHz mono PCM path uses the bundled audio front end. MultiNet runs on core 0
while waiting, sharing that core with the audio front end. Face inference waits
until a real phrase match. During an awake session, phoneme inference pauses and
face inference runs on core 0 instead. Preview/display runs on core 1; the combined
build also places network/Opus work on core 1. A single task owns microphone reads.

An initial extra 0.70 output-score check rejected valid engine detections. The
current gate uses MultiNet's DETECTED state and matching command ID. The engine
threshold setting is 0.70; its reported phrase score is a separate diagnostic
value. Those scores are not calibrated accuracy measurements.

The owner confirmed **it wakes for Hey Deskter and stays waiting otherwise** in
a short test. No long noise/false-trigger benchmark or end-of-phrase latency test
has been performed. The phoneme NN took about 18-19 ms per 32 ms audio chunk.
Moving it off the display core restored the preview to about 11 FPS. This does not
establish that MultiNet uses less power than a dedicated trained wake-word model.

## Awake behavior

Camera preview stays on while waiting, with face inference gated off. A matched
phrase activates face inference and requests a voice session. The awake timeout
is 60 seconds; actual server activity extends it. The gate resumes after timeout.
No sound-level threshold, manual test command, fake detection or transcript can
trigger wake-up. Incoming TTS suppresses mic upload and wake inference to avoid
self-triggering. Conversation uses half-duplex audio, without echo cancellation.

## First-time setup (combined firmware)

1. Connect a phone/computer to Wi-Fi **Deskter Setup**, password **deskter123**.
2. Open **http://192.168.4.1/** and enter the home 2.4 GHz Wi-Fi name and password.
   Credentials stay in device NVS and are not printed or compiled into firmware.
   Alternatively, USB accepts one newline-terminated JSON command with `cmd` set
   to `wifi`, `ssid` and `password` fields. The device does not echo its payload.
   Do not put real credentials in a tracked file or serial capture.
3. Read the activation code on the TFT/serial log, or listen if the service
   speaks the code after the first wake. Sign in at **xiaozhi.me**
   and bind the new device using that code. The firmware polls activation status.
4. Ready means connection settings are available, not proof of account binding.
   Say **Hey Deskter**, pause for the
   listening indication, then speak. Test an actual spoken reply on the speaker.

The official service supplies connection/authentication settings. Device Client-Id
is a persisted random UUID. HTTPS/WSS use the bundled CA trust store and SNTP
clock. No insecure-TLS fallback is used. Firmware/asset updates returned by the
service are not applied; this custom Arduino hardware build is retained.

The client supports the documented WebSocket protocol and Opus audio framing
versions 1/2/3. If the service does not issue secure WebSocket settings, the
firmware reports that state; an MQTT-only deployment is not implemented here.
Mic audio is encoded as16 kHz mono 60 ms Opus frames. The decoder outputs 24 kHz mono
to the existing amplifier DIN 6/BCLK 43/WS 44. Decoded samples are sent at 100%
digital volume, with no attenuation. This replaces the earlier 30% setting.
The mic uses I2S0 PDM RX and the amplifier uses the remaining I2S peripheral.

## Flash layout and dependencies

The provided 16 MB ESP_SR reference partition table does not fit this board.
The sketch supplies an 8 MB `partitions.csv`: one 4 MB app at 0x10000, model image at
0x410000 (0x260000 bytes reserved), existing SPIFFS at 0x670000 and coredump at
0x7F0000. NVS/otadata offsets stay unchanged. There is no second app/OTA slot.

`build.ps1 -Upload -Port COM3` flashes the speech image before the application.
The bundled `srmodels.bin` is 2,468,362 bytes, SHA256:
`2bb881de0511ad2cce5b19d10997351075b73f9f5527d6db5a98bb44f1258497`.
Its unused HiESP wake model is not enabled; custom phrase detection uses MultiNet.

Dependencies already installed: LovyanGFX 1.3.0, ArduinoJson 7.4.3, WebSockets 2.7.2,
esp32_opus 1.0.3; camera/I2S/SR/Wi-Fi/HTTPS/WebServer/Preferences come from Core 3.0.7.
The original flash recovery copy is `arduino/recovery/original_flash.zip`.
Old project archives were permanently removed; see [cleanup](../CLEANUP.md).

## Diagnostics

`AUDIO` prints signal RMS/peak, model chunk time, read errors and outgoing-PCM
queue drops. `PHONEME` and `WAKE` identify actual engine detections. `VOICE`
reports Wi-Fi/config/handshake state, real audio packet counts and errors. Tokens,
Wi-Fi passwords and recognized conversation text are not logged. `MEMORY`
includes internal heap, minimum heap, reset reason and free task stacks. Existing
LIVE/THERMAL logs remain. Face inference and TLS handshakes share a mutex to
avoid overlapping their scratch-memory peaks. The application and detector use
8 KiB stacks; the voice task uses 32 KiB because Opus uses stack allocations.
Its non-played encode/decode self-check left about 7.3 KiB stack headroom.

Core 3.0.7 ships a 2 KiB camera task. A captured crash decoded to its frame-queue
error logging through newlib/diagnostics during Wi-Fi startup. The sketch disables
`cam_hal` logging to avoid that stack-heavy path; application capture/error
counters remain enabled. A subsequent 55-second startup/connection-attempt capture had no panic or camera
capture errors, with about 11.1 FPS preview. Two direct ROM camera-overflow
messages occurred when the fallback AP started; one preview interval fell to
6.5 FPS. This verifies the logging workaround during connection attempts, not
full Wi-Fi/voice operation.

The client reports disconnect reason codes and scans for the configured network
after a 25-second failed connection attempt. It keeps the fallback setup portal
available and retries saved Wi-Fi every 30 seconds. It reports the network
channel and RSSI without printing the home password.

Latest application: 2,491,024 bytes; program usage 2,490,661 bytes;
static RAM 70,716 bytes. SHA256:
`c81ce1bb6301c7680176e27c8086d09c095eeb5d04e8f767625611013bf0a3e7`.
Build/upload passed with flash hash verification. See local ignored logs
`volume_build.log`, `volume_upload.log` and `volume_runtime.log`.
Activation verification is in `activation_runtime.log`.
Detailed combined audio/face evidence is in `voice_handshake_runtime.log`.
Account binding is server-confirmed; English conversation after binding remains unverified.

The first WebSocket build ended extra HTTP headers with CRLF; the WebSockets
library adds that itself before its own User-Agent header. This prematurely
ended the HTTP request, leaving invalid plaintext in the upgraded connection.
Removing the duplicate terminator fixed the immediate disconnect. The server
then accepted hello and returned real STT/TTS. During the combined test, minimum
internal heap was about 10-18 KiB, preview generally 9-11 FPS, microphone read
errors and voice audio errors stayed zero. PCM queue drops occurred during the
initial handshake; the counter did not continue increasing during streaming.
These short captures do not establish long-term stability or thermal behavior.

The early wake-only build had no PCM consumer, so its awake queue-drop count grew;
the combined voice task drains audio while offline and consumes it while listening.
Do not interpret wake-only queue drops as a microphone-read failure.

## Primary sources

- [MultiNet phoneme customization](https://docs.espressif.com/projects/esp-sr/en/latest/esp32/speech_command_recognition/README.html)
- [ArduinoCore 3.0.7 speech example and G2P tools](https://github.com/espressif/arduino-esp32/tree/3.0.7/libraries/ESP_SR)
- [Xiaozhi activation interface](https://github.com/78/xiaozhi-esp32/blob/main/docs/ota.md)
- [Xiaozhi WebSocket/audio protocol](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md)

## Current Wi-Fi and voice validation

The disconnected external antenna explained the failed connection: the board
scanned the network at -86 dBm and reported no-AP/timeout reasons. With the
antenna connected it joined channel 6 at -43 dBm, received a DHCP address and
completed HTTPS configuration (HTTP 200). Saved Wi-Fi settings survived reboot.
The home password is absent from sketch files and logs.

The corrected handshake accepted server hello. One combined capture transmitted
702 microphone Opus packets and decoded/wrote 55 incoming packets with zero
audio errors; live face scores reached 0.9956 with fresh overlays in the same
session. Internal die-temperature readings reached 61-64 C in short active
tests. These are internal sensor readings, not surface temperature or a power
measurement. A long soak, noisy-room speech accuracy and English-agent setup
remain outstanding. Do not describe this model as a proven low-power wake word.

Final post-upload capture: Wi-Fi/config/hello remained ready, with 404 outgoing
and 19 incoming Opus packets and zero reported voice/microphone-read errors.
No panic or camera capture timeout was captured. Minimum internal heap reached
10,280 bytes; this is limited headroom and needs long-run validation. One ROM
camera VSYNC overflow message occurred, so dropped camera frames are possible.

## Activation verification

After the identity correction, configuration HTTP 200 included server_time,
firmware, mqtt, websocket and activation. The actual activation code was sent
to the owner for entry in the platform. Polling returned HTTP 202, then HTTP
200. The next configuration response omitted activation; ready became 1.
Preview stayed near 11.1 FPS while waiting; no camera capture or mic-read errors
were reported. The pre-change archive arduino_before_activation_identity.zip
was CRC-verified before flashing. This test establishes device binding, not
English-agent configuration or long-term combined voice/face stability.

## Speaker volume

At the owner's request, playback now sends the decoded 16-bit PCM samples
unchanged to I2S: 100% digital level. The previous multiplication by 3/10
was removed. No additional gain or clipping is applied in firmware.
