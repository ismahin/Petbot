#include <Arduino.h>
#include <ESP_I2S.h>
#include <esp32-hal-sr.h> // Arduino library discovery also stages the bundled srmodels.bin.
#include <atomic>
#include <cmath>
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_afe_sr_models.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"
#include "freertos/stream_buffer.h"
#include "WakeAudio.hpp"
#include "Settings.hpp"
#include "Session.hpp"
#include "CameraMode.hpp"

namespace {
I2SClass microphone;
const esp_afe_sr_iface_t *afe = nullptr;
esp_afe_sr_data_t *afeData = nullptr;
esp_mn_iface_t *multinet = nullptr;
model_iface_data_t *modelData = nullptr;
srmodel_list_t *models = nullptr;
int feedSamples = 0, fetchSamples = 0;
int16_t *feedBuffer = nullptr;
StreamBufferHandle_t outgoing = nullptr;
StaticStreamBuffer_t outgoingControl;
std::atomic<bool> isSpeaking{false};
std::atomic<uint32_t> readErrors{0}, droppedBytes{0};

void feedTask(void *) {
    for (;;) {
        const size_t required = feedSamples*sizeof(int16_t);
        const size_t got = microphone.readBytes(reinterpret_cast<char *>(feedBuffer),required);
        if (got != required) {
            readErrors.fetch_add(1);
            memset(reinterpret_cast<uint8_t *>(feedBuffer)+got,0,required-got);
        }
        afe->feed(afeData,feedBuffer);
    }
}

void detectTask(void *) {
    uint64_t inferenceUs = 0, samples = 0, squares = 0;
    uint32_t chunks = 0, peak = 0, lastReport = millis();
    bool recognizing = false;
    uint32_t commandUntil=0;
    for (;;) {
        auto *res = afe->fetch(afeData);
        if (!res || res->ret_value == ESP_FAIL || !res->data || res->data_size != fetchSamples*int(sizeof(int16_t))) {
            readErrors.fetch_add(1); vTaskDelay(1); continue;
        }
        const uint32_t now = millis();
        for (int i=0;i<fetchSamples;++i) {
            const int32_t sample = res->data[i];
            squares += int64_t(sample)*sample;
            peak = std::max<uint32_t>(peak,std::abs(sample));
        }
        samples += fetchSamples;

        // The phrase gate runs locally. While awake, reserve its NN time for
        // face inference and the real voice session; suppress TTS self-trigger.
        if ((!session::active() || int32_t(commandUntil-now)>0) && !isSpeaking.load()) {
            { // Continuous frames preserve the start of "Hey"; VAD is diagnostic.
                recognizing = true;
                const int64_t start = esp_timer_get_time();
                const auto state = multinet->detect(modelData,res->data);
                inferenceUs += esp_timer_get_time()-start; ++chunks;
                if (state == ESP_MN_STATE_DETECTED) {
                    const auto *result = multinet->get_results(modelData);
                    if (result && result->num > 0) {
                        Serial.printf("PHONEME command=%d score=%.3f\n",result->command_id[0],double(result->prob[0]));
                        // MultiNet has already applied its detection decision.
                        // Its reported phrase score is not the threshold setter's
                        // scale; applying that threshold again rejected real matches.
                        if (result->command_id[0] == 1 && std::isfinite(result->prob[0])) {
                            session::wake(result->prob[0]);
                            commandUntil=now+4000; // Preserve the trailing "open camera" after Hey Deskter.
                        } else if(std::isfinite(result->prob[0]) && (result->command_id[0]==2 || result->command_id[0]==3)) {
                            cameramode::request(result->command_id[0]==2);
                            commandUntil=0;
                            // This local hardware command works without a cloud reply.
                            session::sleep();
                        }
                    }
                    multinet->clean(modelData); recognizing = false;
                } else if (state == ESP_MN_STATE_TIMEOUT) {
                    multinet->clean(modelData); recognizing = false;
                }
            }
        } else if (recognizing) { multinet->clean(modelData); recognizing = false; }

        if (session::active() && !isSpeaking.load()) {
            const size_t bytes = fetchSamples*sizeof(int16_t);
            const size_t sent = xStreamBufferSend(outgoing,res->data,bytes,0);
            droppedBytes.fetch_add(bytes-sent);
        }
        if (now-lastReport >= 5000) {
            Serial.printf("AUDIO rms=%.0f peak=%lu vad=%u wake_nn=%.1f ms chunks=%lu read_errors=%lu queue_drop=%lu active=%u\n",
                samples ? std::sqrt(double(squares)/samples) : 0, (unsigned long)peak,
                unsigned(res->vad_state), chunks ? inferenceUs/(1000.0*chunks) : 0,
                (unsigned long)chunks,(unsigned long)readErrors.load(),(unsigned long)droppedBytes.load(),unsigned(session::active()));
            samples=squares=inferenceUs=0; chunks=peak=0; lastReport=now;
        }
    }
}
}

namespace wakeaudio {
bool begin() {
    models=esp_srmodel_init("model");
    if (!models) { Serial.println("AUDIO missing speech model partition/image"); return false; }
    char *name=esp_srmodel_filter(models,ESP_MN_PREFIX,ESP_MN_ENGLISH);
    if (!name || strncmp(name,"mn5",3) != 0) { Serial.println("AUDIO requires bundled phoneme-based MultiNet5 English"); return false; }
    multinet=esp_mn_handle_from_name(name);
    if (!multinet || !(modelData=multinet->create(name,4000))) return false;
    if (esp_mn_commands_alloc(multinet,modelData) != ESP_OK) return false;
    // Arduino's official G2P alphabet: HH=h EY=d D=D EH=f S=S K=K T=T ER=k.
    // Literal Desk-ter plus Dexter pronunciation, both mapped to the same wake ID.
    if (esp_mn_commands_add(1,const_cast<char *>("hd DfSKTk")) != ESP_OK ||
        esp_mn_commands_add(1,const_cast<char *>("hd DfKSTk")) != ESP_OK ||
        esp_mn_commands_add(2,const_cast<char *>("bPcN KaMkc")) != ESP_OK ||
        esp_mn_commands_add(2,const_cast<char *>("bPcN KaMRc")) != ESP_OK ||
        esp_mn_commands_add(2,const_cast<char *>("hd DfSKTk bPcN KaMkc")) != ESP_OK ||
        esp_mn_commands_add(2,const_cast<char *>("hd DfKSTk bPcN KaMkc")) != ESP_OK ||
        esp_mn_commands_add(3,const_cast<char *>("KLbZ KaMkc")) != ESP_OK ||
        esp_mn_commands_add(3,const_cast<char *>("KLbZ KaMRc")) != ESP_OK ||
        esp_mn_commands_add(3,const_cast<char *>("hd DfSKTk KLbZ KaMkc")) != ESP_OK ||
        esp_mn_commands_add(3,const_cast<char *>("hd DfKSTk KLbZ KaMkc")) != ESP_OK || esp_mn_commands_update()) return false;
    const int thresholdResult=multinet->set_det_threshold(modelData,settings::wakeThreshold);
    Serial.printf("AUDIO engine threshold setter returned %d\n",thresholdResult);

    afe_config_t config{};
    config.aec_init=false; config.se_init=false; config.vad_init=true; config.wakenet_init=false;
    config.vad_mode=VAD_MODE_3; config.afe_mode=SR_MODE_LOW_COST;
    config.afe_perferred_core=0; config.afe_perferred_priority=5; config.afe_ringbuf_size=12;
    config.memory_alloc_mode=AFE_MEMORY_ALLOC_MORE_PSRAM; config.afe_linear_gain=1.0f;
    config.agc_mode=AFE_MN_PEAK_AGC_MODE_2; config.pcm_config={1,1,0,16000};
    config.afe_ns_mode=NS_MODE_SSP; config.fixed_first_channel=true;
    afe=&ESP_AFE_SR_HANDLE;
    afeData=afe->create_from_config(&config);
    if (!afeData) return false;
    feedSamples=afe->get_feed_chunksize(afeData); fetchSamples=afe->get_fetch_chunksize(afeData);
    if (feedSamples <= 0 || fetchSamples != multinet->get_samp_chunksize(modelData) || afe->get_total_channel_num(afeData) != 1) return false;
    feedBuffer=static_cast<int16_t *>(heap_caps_malloc(feedSamples*sizeof(int16_t),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
    constexpr size_t queueBytes=640000; // Bounded 20-second question buffer during a cold WSS handshake.
    auto *storage=static_cast<uint8_t *>(heap_caps_malloc(queueBytes+1,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if (!feedBuffer || !storage) return false;
    outgoing=xStreamBufferCreateStatic(queueBytes+1,1,storage,&outgoingControl);
    if (!outgoing) return false;
    microphone.setPinsPdmRx(settings::micClock,settings::micData);
    microphone.setTimeout(1000);
    if (!microphone.begin(I2S_MODE_PDM_RX,16000,I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_MONO)) {
        Serial.printf("AUDIO PDM init error=%d\n",microphone.lastError()); return false;
    }
    Serial.printf("AUDIO model=%s phrase=Hey Deskter rate=16000 feed=%d fetch=%d PDM=42/41 threshold=%.2f\n",name,feedSamples,fetchSamples,double(settings::wakeThreshold));
    if (xTaskCreatePinnedToCore(feedTask,"mic_feed",6144,nullptr,5,nullptr,0) != pdPASS) return false;
    if (xTaskCreatePinnedToCore(detectTask,"phoneme_gate",12288,nullptr,3,nullptr,0) != pdPASS) return false;
    return true;
}
size_t readPcm(void *destination,size_t maximumBytes) { return outgoing ? xStreamBufferReceive(outgoing,destination,maximumBytes,0) : 0; }
void discardPcm() {
    uint8_t scratch[512];
    while (readPcm(scratch,sizeof(scratch))) {}
}
void setSpeaking(bool value) { isSpeaking.store(value); }
bool speaking() { return isSpeaking.load(); }
}
