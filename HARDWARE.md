# Hardware context

Source: owner-provided configuration, 2026-11-13. GPIO values below are ESP32-S3
numbers. Preserve these connections when integrating other robot features.

| Hardware | Status |
| --- | --- |
| XIAO ESP32S3 Sense, 8 MB flash / 8 MB OPI PSRAM | Owner's board configuration |
| OV3660 camera at 320 x 240 RGB565, 20 MHz XCLK | PID 0x3660 and live preview confirmed with the current Arduino implementation |
| ST7789 240 x 320 panel, rotation 1 = 320 x 240 | Reported working with LovyanGFX |
| MAX98357A-style module, 8 ohm / 1 W speaker | Output previously tested; exact module unverified |
| Onboard PDM microphone | Live 16 kHz mono capture and Hey Deskter wake phrase confirmed; zero read errors in captured tests |
| Edge Impulse Face_detection_inferencing FOMO library | Compiled after patches; successful detection not established |
| Arduino bundled MSR01/MNP01 detector | Active firmware; real live detections and green boxes following the face confirmed by owner |
| Xiaozhi AI | Arduino network/audio client added; connection and conversation validation in progress |
| Petting, emotion system | Future work |

| Function | GPIO |
| --- | --- |
| TFT CS / DC / RESET | 1 / 2 / 4 |
| TFT SCK / MOSI / MISO | 7 / 9 / disconnected |
| Camera XCLK / SDA / SCL | 10 / 40 / 39 |
| Camera D0..D7 | 15, 17, 18, 16, 14, 12, 11, 48 |
| Camera VSYNC / HREF / PCLK | 38 / 47 / 13 |
| Camera PWDN / RESET | -1 / -1 |
| Amplifier DIN / BCLK / WS | 6 / 43 / 44 |
| PDM CLK / DATA | 42 / 41 |
| Sense microSD SCK / MISO / MOSI / CS | 7 / 8 / 9 / 21 |

The Arduino application uses Hardware CDC/JTAG for USB logs. The PDM microphone
and I2S speaker use separate I2S peripherals; cloud voice uses half-duplex audio.
Using the default UART0 console would use GPIO43/44 assigned to the amplifier.
The expansion-board microSD CS (GPIO21) is held high. SD is not mounted. TFT and SD
share SCK/MOSI: future SD use requires a common bus implementation and coordinated
transactions; enabling a second independent SPI driver is insufficient.

Keep the existing working TFT VCC connection. Its exact supply voltage and the
module's requirements still need identification. The prior backlight plan uses 3V3.
This firmware changes no power wiring. Development is USB-C powered.

Available battery: 3.7 V nominal, 2000 mAh LiPo. Battery polarity, wiring, charging,
load budget, regulator capacity, amplifier markings and TFT supply remain unverified.

The original Arduino setup is Core 3.0.7, XIAO ESP32S3 board, OPI PSRAM,
115200 baud, LovyanGFX, esp_camera and ESP_I2S. Edge Impulse remains installed at
`C:\Users\ismahin\Documents\Arduino\libraries\Face_detection_inferencing`.
It is not used or modified by the active Arduino face-detection sketch.
