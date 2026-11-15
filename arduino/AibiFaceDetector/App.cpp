#include <Arduino.h>
#include <algorithm>
#include <cmath>
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_log.h"
#include "driver/temperature_sensor.h"
#include "human_face_detect_msr01.hpp"
#include "human_face_detect_mnp01.hpp"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "App.hpp"
#include "Settings.hpp"
#include "PoseTransform.hpp"
#include "Tft.hpp"
#include "Session.hpp"
#include "WakeAudio.hpp"
#include "Voice.hpp"

SET_LOOP_TASK_STACK_SIZE(8192); // Measured peak under 3 KiB; retain over 5 KiB headroom.

#if !CONFIG_IDF_TARGET_ESP32S3 || !defined(BOARD_HAS_PSRAM)
#error "Select XIAO ESP32S3 with OPI PSRAM enabled."
#endif

namespace {
struct Face { int x1, y1, x2, y2; float score; };
struct Result {
    uint32_t sequence;
    int64_t capturedUs;
    uint32_t inferenceUs;
    uint32_t preprocessUs;
    uint64_t totalInferenceUs;
    uint32_t completedRuns;
    int rollDegrees;
    unsigned quarterTurns;
    bool mirrored;
    float bestRefinedScore;
    unsigned candidates, count;
    Face faces[settings::maxFaces];
};
struct Job { uint32_t sequence; int64_t capturedUs; uint8_t poseIndex; uint32_t preprocessUs; };
PetDisplay lcd;
uint8_t *snapshot = nullptr;
QueueHandle_t freeSnapshot = nullptr, jobs = nullptr, results = nullptr;
TaskHandle_t detectorHandle = nullptr;
bool displayReady = false;
temperature_sensor_handle_t temperatureSensor = nullptr;

[[noreturn]] void fail(const char *message) {
    Serial.printf("FATAL: %s\n", message);
    if (displayReady) {
        lcd.fillScreen(TFT_BLACK);
        lcd.setTextColor(TFT_RED, TFT_BLACK);
        lcd.setCursor(4, 4);
        lcd.println(message);
    }
    while (true) delay(1000);
}

void checkQueue(BaseType_t status) {
    if (status != pdTRUE) { Serial.println("FATAL: snapshot ownership queue failed"); abort(); }
}

int clamp(int value, int upper) { return std::max(0, std::min(value, upper)); }

void copyForInference(uint8_t *destination, const uint8_t *source, uint8_t poseIndex) {
    const auto p = pose::specification(poseIndex);
    const int turn = p.quarterTurns;
    if (p.tiltDegrees != 0) {
        const auto t = pose::toCamera(poseIndex);
        // Fixed-point increments avoid per-pixel trigonometry/floating arithmetic.
        const int32_t xx = std::lround(t.xx*65536), xy = std::lround(t.xy*65536);
        const int32_t yx = std::lround(t.yx*65536), yy = std::lround(t.yy*65536);
        int32_t rowX = std::lround(t.x0*65536) + 32768;
        int32_t rowY = std::lround(t.y0*65536) + 32768;
        for (int y = 0; y < p.height; ++y, rowX += xy, rowY += yy) {
            int32_t sampleX = rowX, sampleY = rowY;
            for (int x = 0; x < p.width; ++x, sampleX += xx, sampleY += yx) {
                const int sx = sampleX >> 16, sy = sampleY >> 16;
                const size_t dst = (y*p.width+x)*2;
                if (sx >= 0 && sx < settings::width && sy >= 0 && sy < settings::height) {
                    const size_t src = (sy*settings::width+sx)*2;
                    destination[dst] = source[src]; destination[dst+1] = source[src+1];
                } else { destination[dst] = 0; destination[dst+1] = 0; }
            }
        }
        return;
    }
    if (turn == 0 && !p.mirrored) { memcpy(destination, source, settings::frameBytes); return; }
    for (int y = 0; y < p.height; ++y) {
        for (int x = 0; x < p.width; ++x) {
            const int u = p.mirrored ? p.width-1-x : x;
            int sx, sy;
            if (turn == 1) { sx = y; sy = settings::height-1-u; }
            else if (turn == 2) { sx = settings::width-1-u; sy = settings::height-1-y; }
            else if (turn == 3) { sx = settings::width-1-y; sy = u; }
            else { sx = u; sy = y; }
            const size_t src = (sy * 320 + sx) * 2;
            const size_t dst = (y*p.width+x)*2;
            destination[dst] = source[src];
            destination[dst + 1] = source[src + 1];
        }
    }
}

Face displayBox(const dl::detect::result_t &face, const pose::Transform &transform) {
    const auto &b = face.box;
    Face f{};
    float minX = INFINITY, minY = INFINITY, maxX = -INFINITY, maxY = -INFINITY;
    for (const int x : {b[0], b[2]}) {
        for (const int y : {b[1], b[3]}) {
            const auto p = transform.map(x, y);
            minX = std::min(minX, p.x); maxX = std::max(maxX, p.x);
            minY = std::min(minY, p.y); maxY = std::max(maxY, p.y);
        }
    }
    f = {int(std::floor(minX)), int(std::floor(minY)), int(std::ceil(maxX)), int(std::ceil(maxY)), face.score};
    f.x1 = clamp(f.x1, 319); f.x2 = clamp(f.x2, 319);
    f.y1 = clamp(f.y1, 239); f.y2 = clamp(f.y2, 239);
    return f;
}

// Verify the fast pixel-copy path against the box transform on a real frame.
// All eight quarter-turn/reflection combinations must agree at the corners
// and interior pixels. Nothing from this check is sent to the detection queue.
bool verifyPixelTransforms() {
    auto *fb = esp_camera_fb_get();
    if (!fb) return false;
    bool valid = fb->buf && fb->len == settings::frameBytes &&
                 fb->width == settings::width && fb->height == settings::height && fb->format == PIXFORMAT_RGB565;
    for (uint8_t index = 0; valid && index < settings::poseCount; ++index) {
        const auto p = pose::specification(index);
        if (p.tiltDegrees != 0) continue;
        copyForInference(snapshot, fb->buf, index);
        const auto transform = pose::toCamera(index);
        for (const int y : {0, p.height/3, p.height/2, p.height-1}) {
            for (const int x : {0, p.width/3, p.width/2, p.width-1}) {
                const auto source = transform.map(x,y);
                const int sx = std::lround(source.x), sy = std::lround(source.y);
                if (sx < 0 || sy < 0 || sx >= settings::width || sy >= settings::height) { valid = false; continue; }
                const size_t dst = (y*p.width+x)*2, src = (sy*settings::width+sx)*2;
                if (snapshot[dst] != fb->buf[src] || snapshot[dst+1] != fb->buf[src+1]) valid = false;
            }
        }
    }
    esp_camera_fb_return(fb);
    return valid;
}

void detectorTask(void *) {
    HumanFaceDetectMSR01 stage1(settings::proposalThreshold, 0.5f, settings::proposalLimit, settings::detectorScale);
    HumanFaceDetectMNP01 stage2(settings::refinementProbeThreshold, 0.3f, settings::refinedFaceLimit);
    Serial.println("Arduino pretrained MSR01 + MNP01 face detector ready");
    uint8_t token = 0; // Snapshot token also selects the next inference angle.
    checkQueue(xQueueSend(freeSnapshot, &token, 0));
    uint64_t totalInferenceUs = 0;
    uint32_t completedRuns = 0;
    pose::Search search;
    const std::vector<int> landscape{settings::height, settings::width, 3};
    const std::vector<int> portrait{settings::width, settings::height, 3};
    for (;;) {
        Job job{};
        if (xQueueReceive(jobs, &job, portMAX_DELAY) != pdTRUE) continue;
        const auto p = pose::specification(job.poseIndex);
        const auto &shape = (p.quarterTurns & 1) ? portrait : landscape;
        session::HeavyWork memoryLease;
        if(!session::active() || esp_timer_get_time()-job.capturedUs>int64_t(settings::maxResultAgeMs)*1000) {
            Result empty{}; empty.completedRuns=completedRuns; empty.totalInferenceUs=totalInferenceUs;
            checkQueue(xQueueOverwrite(results,&empty)); token=job.poseIndex;
            checkQueue(xQueueSend(freeSnapshot,&token,0)); continue;
        }
        const int64_t started = esp_timer_get_time();
        // This uint16_t camera-buffer API is used by Arduino Core 3.0.7's
        // CameraWebServer. It understands the camera's MSB-first RGB565 layout.
        auto &candidates = stage1.infer(reinterpret_cast<uint16_t *>(snapshot), shape);
        auto &found = stage2.infer(reinterpret_cast<uint16_t *>(snapshot), shape, candidates);
        Result output{};
        output.rollDegrees = p.tiltDegrees;
        output.quarterTurns = p.quarterTurns;
        output.mirrored = p.mirrored;
        output.preprocessUs = job.preprocessUs;
        const auto transform = pose::toCamera(job.poseIndex);
        output.sequence = job.sequence;
        output.capturedUs = job.capturedUs;
        output.inferenceUs = esp_timer_get_time() - started;
        totalInferenceUs += output.inferenceUs;
        output.totalInferenceUs = totalInferenceUs;
        output.completedRuns = ++completedRuns;
        output.candidates = candidates.size();
        for (const auto &face : found) {
            if (std::isfinite(face.score) && face.score >= 0 && face.score <= 1)
                output.bestRefinedScore = std::max(output.bestRefinedScore, face.score);
            if (face.box.size() != 4 || !std::isfinite(face.score) || face.score < settings::faceThreshold || face.score > 1) continue;
            const Face f = displayBox(face, transform);
            if (f.x2 <= f.x1 || f.y2 <= f.y1 || output.count >= settings::maxFaces) continue;
            output.faces[output.count++] = f;
        }
        checkQueue(xQueueOverwrite(results, &output)); // Zero faces clears previous detections.
        token = search.next(job.poseIndex, output.count != 0);
        checkQueue(xQueueSend(freeSnapshot, &token, 0));
        vTaskDelay(1);
    }
}

void sensorSetting(const char *name, int (*fn)(sensor_t *, int), sensor_t *sensor, int value) {
    if (!fn || fn(sensor, value) != 0) Serial.printf("Sensor setting unavailable: %s\n", name);
}

bool initCamera() {
    // Core 3.0.7 ships a 2 KiB cam_task. Its frame-queue error logging
    // overflows that stack through newlib/diagnostics when Wi-Fi starts.
    // Avoid that unsafe logging path; application capture counters remain on.
    esp_log_level_set("cam_hal", ESP_LOG_NONE);
    camera_config_t c{};
    c.pin_pwdn = c.pin_reset = -1;
    c.pin_xclk = 10; c.pin_sccb_sda = 40; c.pin_sccb_scl = 39;
    c.pin_d0 = 15; c.pin_d1 = 17; c.pin_d2 = 18; c.pin_d3 = 16;
    c.pin_d4 = 14; c.pin_d5 = 12; c.pin_d6 = 11; c.pin_d7 = 48;
    c.pin_vsync = 38; c.pin_href = 47; c.pin_pclk = 13;
    c.xclk_freq_hz = 20000000;
    c.ledc_timer = LEDC_TIMER_0; c.ledc_channel = LEDC_CHANNEL_0;
    c.pixel_format = PIXFORMAT_RGB565; c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 12;
    c.fb_location = CAMERA_FB_IN_PSRAM;
    c.fb_count = 2; c.grab_mode = CAMERA_GRAB_LATEST;
    esp_err_t err = esp_camera_init(&c);
    if (err != ESP_OK) {
        Serial.printf("Two-buffer camera init: %s; retrying single buffer\n", esp_err_to_name(err));
        esp_camera_deinit();
        c.fb_count = 1; c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
        err = esp_camera_init(&c);
    }
    if (err != ESP_OK) { Serial.printf("Camera init error: %s\n", esp_err_to_name(err)); return false; }
    auto *sensor = esp_camera_sensor_get();
    if (!sensor) return false;
    Serial.printf("Camera PID=0x%04x, RGB565 320x240, buffers=%u\n", sensor->id.PID, unsigned(c.fb_count));
    sensorSetting("auto exposure", sensor->set_exposure_ctrl, sensor, 1);
    sensorSetting("auto gain", sensor->set_gain_ctrl, sensor, 1);
    sensorSetting("auto white balance", sensor->set_whitebal, sensor, 1);
    sensorSetting("lens correction", sensor->set_lenc, sensor, 1);
    sensorSetting("mirror", sensor->set_hmirror, sensor, settings::cameraMirror);
    sensorSetting("flip", sensor->set_vflip, sensor, settings::cameraFlip);
    return true;
}

}

void appSetup() {
    Serial.begin(115200);
    const uint32_t waitStart = millis();
    while (!Serial && millis() - waitStart < 1500) delay(10);
    if (!setCpuFrequencyMhz(settings::cpuMHz)) fail("Cannot set CPU frequency");
    heap_caps_malloc_extmem_enable(4096); // Keep small/DMA allocations internal; larger general buffers use PSRAM.
    if(!session::begin()) fail("Memory coordination init failed");
    Serial.println("\nAIBI Arduino face detector / ESP32 Core 3.0.7");
    Serial.printf("BOOT reset_reason=%d (1=power, 3=software, 4=panic, 5/6/7=watchdog, 9=brownout)\n", int(esp_reset_reason()));
    if (!pose::geometryValid()) fail("Inference geometry self-check failed");
    Serial.println("GEOMETRY 24 rotation/tilt/mirror transforms and search coverage passed");
    temperature_sensor_config_t temperatureConfig = TEMPERATURE_SENSOR_CONFIG_DEFAULT(20, 100);
    if (temperature_sensor_install(&temperatureConfig, &temperatureSensor) == ESP_OK) {
        if (temperature_sensor_enable(temperatureSensor) != ESP_OK) temperatureSensor = nullptr;
    } else temperatureSensor = nullptr;
    Serial.printf("PSRAM=%u bytes, internal free=%u\n", unsigned(ESP.getPsramSize()), unsigned(ESP.getFreeHeap()));
    if (!psramFound()) fail("Enable OPI PSRAM");
    digitalWrite(settings::sdCs, HIGH);
    pinMode(settings::sdCs, OUTPUT);
    if (!lcd.init()) fail("ST7789 initialization failed");
    displayReady = true;
    lcd.setColorDepth(16); lcd.setRotation(1); lcd.setSwapBytes(false); lcd.initDMA();
    lcd.fillScreen(TFT_BLACK);
    lcd.setTextColor(TFT_WHITE, TFT_BLACK); lcd.setCursor(8, 8);
    lcd.println("AIBI Arduino / face detection");
    lcd.println("TFT test: R G B W");
    const uint32_t colors[] = {TFT_RED, TFT_GREEN, TFT_BLUE, TFT_WHITE};
    for (int i = 0; i < 4; ++i) lcd.fillRect(i * 80, 60, 80, 80, colors[i]);
    delay(800);
    if (!initCamera()) fail("Camera initialization failed");
    snapshot = static_cast<uint8_t *>(heap_caps_malloc(settings::frameBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!snapshot) fail("Inference snapshot allocation failed");
    if (!verifyPixelTransforms()) fail("Rotation/mirror pixel check failed");
    Serial.println("PIXELS all 8 quarter-turn/reflection copy-to-box mappings passed");
    if (!wakeaudio::begin()) fail("Microphone/phoneme model init failed");
    if (!voice::begin()) fail("Voice codec/speaker/task init failed");
    freeSnapshot = xQueueCreate(1, sizeof(uint8_t)); jobs = xQueueCreate(1, sizeof(Job)); results = xQueueCreate(1, sizeof(Result));
    if (!snapshot || !freeSnapshot || !jobs || !results) fail("Inference allocation failed");
    if (xTaskCreatePinnedToCore(detectorTask, "face_detect", 8192, nullptr, 1, &detectorHandle, 0) != pdPASS)
        fail("Cannot create detector task");
    Serial.println("Preview active; say Hey Deskter to activate real face inference");
}

void appLoop() {
    voice::pollSerial();
    static uint32_t sequence = 0, frames = 0, errors = 0, lastSnapshotMs = 0;
    static uint32_t reportStart = millis();
    static int64_t displayTotal = 0;
    static uint32_t lastMemoryReport = 0;
    static int64_t lastThermalReportUs = 0;
    static uint64_t previousInferenceUs = 0;
    static uint32_t previousRuns = 0;
    auto *fb = esp_camera_fb_get();
    if (!fb) { ++errors; Serial.println("Camera capture timeout"); delay(20); return; }
    if (!fb->buf || fb->format != PIXFORMAT_RGB565 || fb->width != 320 || fb->height != 240 || fb->len != settings::frameBytes) {
        ++errors; Serial.printf("Invalid frame: %ux%u bytes=%u\n", unsigned(fb->width), unsigned(fb->height), unsigned(fb->len));
        esp_camera_fb_return(fb); delay(1); return;
    }
    ++sequence;
    int64_t captured = int64_t(fb->timestamp.tv_sec) * 1000000 + fb->timestamp.tv_usec;
    const int64_t now = esp_timer_get_time();
    if (captured <= 0 || captured > now) captured = 0;
    const bool active = session::active();
    if (active && millis() - lastSnapshotMs >= settings::inferenceIntervalMs) {
        uint8_t token;
        if (xQueueReceive(freeSnapshot, &token, 0) == pdTRUE) {
            const int64_t copyStarted = esp_timer_get_time();
            copyForInference(snapshot, fb->buf, token);
            const Job job{sequence, captured, token, uint32_t(esp_timer_get_time()-copyStarted)};
            checkQueue(xQueueSend(jobs, &job, 0));
            lastSnapshotMs = millis();
        }
    }
    Result latest{};
    const bool haveResult = xQueuePeek(results, &latest, 0) == pdTRUE;
    const int64_t displayStart = esp_timer_get_time();
    const bool fresh = active && haveResult && captured > 0 && latest.capturedUs > 0 && latest.capturedUs <= captured &&
                       displayStart - latest.capturedUs <= int64_t(settings::maxResultAgeMs) * 1000;
    lcd.startWrite();
    lcd.pushImageDMA(0, 0, 320, 240, reinterpret_cast<const uint16_t *>(fb->buf));
    lcd.waitDMA(); // Camera frame remains owned until the transfer completes.
    if (fresh) {
        for (unsigned i = 0; i < latest.count; ++i) {
            const auto &f = latest.faces[i];
            lcd.drawRect(f.x1, f.y1, f.x2-f.x1+1, f.y2-f.y1+1, TFT_GREEN);
            if (f.x2-f.x1 > 3 && f.y2-f.y1 > 3)
                lcd.drawRect(f.x1+1, f.y1+1, f.x2-f.x1-1, f.y2-f.y1-1, TFT_GREEN);
            lcd.setTextColor(TFT_GREEN, TFT_BLACK);
            lcd.setCursor(std::min(f.x1, 260), f.y1 >= 10 ? f.y1-10 : f.y1+2);
            lcd.printf("face %.2f", double(f.score));
        }
    }
    char status[96]; session::getStatus(status,sizeof(status));
    lcd.setTextColor(active ? TFT_GREEN : TFT_WHITE,TFT_BLACK);
    lcd.setCursor(2,228);
    lcd.printf("%s",active ? "Deskter awake / face detection" : "Say Hey Deskter");
    if (status[0]) { lcd.setTextColor(TFT_WHITE,TFT_BLACK); lcd.setCursor(2,2); lcd.printf("%.51s",status); }
    lcd.endWrite();
    displayTotal += esp_timer_get_time() - displayStart;
    esp_camera_fb_return(fb);
    ++frames;
    const uint32_t reportNow = millis();
    if (reportNow - reportStart >= 1000) {
        Serial.printf("LIVE uptime=%lu s preview=%.1f fps display=%.1f ms errors=%lu faces=%u candidates=%u infer=%.1f ms prep=%.1f ms turn=%u roll=%d mirror=%u best=%.3f overlay=%s\n",
                      static_cast<unsigned long>(reportNow / 1000),
                      frames * 1000.0 / (reportNow-reportStart), displayTotal / (frames * 1000.0),
                      static_cast<unsigned long>(errors), latest.count, latest.candidates, latest.inferenceUs / 1000.0,
                      latest.preprocessUs / 1000.0, latest.quarterTurns*90, latest.rollDegrees,
                      unsigned(latest.mirrored), double(latest.bestRefinedScore),
                      fresh ? "fresh" : "waiting/expired");
        for (unsigned i = 0; i < latest.count; ++i) {
            const auto &f = latest.faces[i];
            Serial.printf("LIVE face[%u] score=%.4f box=[%d,%d,%d,%d]\n", i, double(f.score), f.x1,f.y1,f.x2,f.y2);
        }
        frames = 0; displayTotal = 0; reportStart = reportNow;
    }
    if (reportNow - lastMemoryReport >= 10000) {
        Serial.printf("MEMORY internal=%u minimum=%u PSRAM=%u stack_free_loop=%u stack_free_detector=%u stack_free_voice=%u reset_reason=%d\n",
                      unsigned(ESP.getFreeHeap()), unsigned(ESP.getMinFreeHeap()), unsigned(ESP.getFreePsram()),
                      unsigned(uxTaskGetStackHighWaterMark(nullptr)), unsigned(uxTaskGetStackHighWaterMark(detectorHandle)), voice::stackFree(),int(esp_reset_reason()));
        lastMemoryReport = reportNow;
    }
    const int64_t thermalNow = esp_timer_get_time();
    if (thermalNow - lastThermalReportUs >= 5000000 && haveResult) {
        float temperature = NAN;
        if (temperatureSensor) temperature_sensor_get_celsius(temperatureSensor, &temperature);
        const double spanUs = thermalNow - lastThermalReportUs;
        Serial.printf("THERMAL die_c=%.1f cpu_mhz=%u nn_hz=%.2f nn_time_pct=%.1f\n", double(temperature),
                      unsigned(getCpuFrequencyMhz()), (latest.completedRuns - previousRuns) * 1000000.0 / spanUs,
                      (latest.totalInferenceUs - previousInferenceUs) * 100.0 / spanUs);
        previousInferenceUs = latest.totalInferenceUs;
        previousRuns = latest.completedRuns;
        lastThermalReportUs = thermalNow;
    }
    delay(1);
}
