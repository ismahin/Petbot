#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_sntp.h"
#include <NetworkClientSecure.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <ESP_I2S.h>
#include <opus.h>
#include <ctime>
#include <cstring>
#include <atomic>
#include <cmath>
#include <algorithm>
#include "esp_app_format.h"
#include "esp_chip_info.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "sys/time.h"
#include "freertos/queue.h"
#include "freertos/idf_additions.h"
#include "Voice.hpp"
#include "Session.hpp"
#include "WakeAudio.hpp"
#include "CameraMode.hpp"

extern const uint8_t deskterCaStart[] asm("_binary_x509_crt_bundle_start");
extern const uint8_t deskterCaEnd[] asm("_binary_x509_crt_bundle_end");

namespace {
constexpr char otaUrl[]="https://api.tenclass.net/xiaozhi/ota/";
constexpr char boardName[]="xiao-esp32s3-sense";
constexpr char firmwareVersion[]="1.0.0";
constexpr char setupSsid[]="Deskter Setup", setupPassword[]="deskter123";
Preferences preferences;
WebServer portal(80);
DNSServer dns;
WebSocketsClient socketClient;
I2SClass speaker;
TaskHandle_t networkHandle=nullptr;
TaskHandle_t playbackHandle=nullptr;
constexpr unsigned playbackQueueFrames=12,playbackPrefillFrames=4;
struct PlaybackPacket { uint32_t epoch; uint16_t length; uint8_t bytes[1500]; };
QueueHandle_t playbackQueue=nullptr;
StaticQueue_t playbackQueueControl;
std::atomic<uint32_t> playbackEpoch{0},playbackLastWrite{0},playbackDrops{0},playbackUnderruns{0};
std::atomic<bool> playbackFinished{true},playbackBusy{false};
struct WifiRequest { char ssid[33],password[65]; };
QueueHandle_t wifiRequests=nullptr;
struct ServerRequest { char url[192],ca[1600],token[257],ntp[64]; uint64_t utc; bool restore; };
QueueHandle_t serverRequests=nullptr;
StaticQueue_t serverQueueControl;
OpusEncoder *encoder=nullptr;
OpusDecoder *decoder=nullptr;
int16_t *inputPcm=nullptr,*outputPcm=nullptr;
uint8_t *encoded=nullptr;
size_t inputBytes=0;
String uuid,deviceId,wifiSsid,wifiPassword,wsUrl,wsToken,wsHeaders,sessionId;
String activationCode;
String otaEndpoint=otaUrl,serverCa,serverAuth,serverNtp;
bool portalActive=false,newWifi=false,ready=false,activating=false,wsStarted=false,helloReady=false,ttsEnding=false;
unsigned protocolVersion=1;
uint32_t wifiStarted=0,nextConfig=0,activationAttempts=0,ttsEnded=0,helloStarted=0;
uint32_t audioSent=0,lastReport=0;
std::atomic<uint32_t> audioReceived{0},audioErrors{0};
std::atomic<int> wifiDisconnectReason{0};
std::atomic<float> outputLevel{0};
std::atomic<int> portalControl{0};
uint32_t manualPortalUntil=0;
bool wifiWasConnected=false,scanPending=false;
uint32_t scanFinishedAt=0;
uint32_t lastWifiRetry=0;

void status(const char *text) { session::setStatus(text); }

void playbackTask(void *) {
    PlaybackPacket packet{};
    uint32_t epoch=0;
    bool primed=false;
    for(;;) {
        const uint32_t current=playbackEpoch.load();
        if(current!=epoch) {
            epoch=current;primed=false;
            opus_decoder_ctl(decoder,OPUS_RESET_STATE);
        }
        if(!wakeaudio::speaking()) {
            outputLevel.store(0);
            // Drain obsolete packets without ever playing them into a new turn.
            xQueueReceive(playbackQueue,&packet,0);
            vTaskDelay(pdMS_TO_TICKS(5));continue;
        }
        if(!primed) {
            const unsigned queued=uxQueueMessagesWaiting(playbackQueue);
            if(queued>=playbackPrefillFrames || (playbackFinished.load() && queued)) primed=true;
            else { vTaskDelay(pdMS_TO_TICKS(2));continue; }
        }
        if(xQueueReceive(playbackQueue,&packet,pdMS_TO_TICKS(10))!=pdTRUE) {
            const uint32_t last=playbackLastWrite.load();
            if(!playbackFinished.load() && last && millis()-last>100) {
                ++playbackUnderruns;primed=false;
            }
            continue;
        }
        if(packet.epoch!=epoch || epoch!=playbackEpoch.load()) continue;
        playbackBusy.store(true);
        const int count=opus_decode(decoder,packet.bytes,packet.length,outputPcm,2880,0);
        if(count<0) ++audioErrors;
        else if(epoch==playbackEpoch.load() && wakeaudio::speaking()) {
            // Only this task owns decoding and blocking I2S writes. Networking
            // remains free to receive the next frame while DMA plays this one.
            const size_t bytes=size_t(count)*sizeof(int16_t);
            if(speaker.write(reinterpret_cast<uint8_t *>(outputPcm),bytes)!=bytes) ++audioErrors;
            uint64_t energy=0;
            for(int i=0;i<count;++i) energy+=int64_t(outputPcm[i])*outputPcm[i];
            outputLevel.store(std::min(1.f,float(std::sqrt(double(energy)/std::max(1,count))/5000.)));
            session::setVisual(session::Visual::Speaking);
            playbackLastWrite.store(millis());++audioReceived;
        }
        playbackBusy.store(false);
    }
}

void makeUuid() {
    uuid=preferences.getString("client","");
    if (uuid.length()==36) return;
    uint8_t raw[16]; esp_fill_random(raw,sizeof(raw));
    raw[6]=(raw[6]&15)|0x40; raw[8]=(raw[8]&63)|0x80;
    char text[37];
    snprintf(text,sizeof(text),"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
        raw[0],raw[1],raw[2],raw[3],raw[4],raw[5],raw[6],raw[7],raw[8],raw[9],raw[10],raw[11],raw[12],raw[13],raw[14],raw[15]);
    uuid=text; preferences.putString("client",uuid);
}

void startPortal() {
    if (portalActive) return;
    WiFi.mode(WIFI_AP_STA);
    if (!WiFi.softAP(setupSsid,setupPassword)) { status("Wi-Fi setup could not start"); return; }
    dns.start(53,"*",WiFi.softAPIP());
    session::setVisual(session::Visual::Setup);
    portal.on("/",HTTP_GET,[] {
        portal.send(200,"text/html; charset=utf-8",R"HTML(<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>Deskter Wi-Fi</title><style>body{font:17px system-ui;margin:36px auto;padding:0 22px;max-width:440px;background:#081419;color:#d8fafa}input,select,button{box-sizing:border-box;width:100%;font:inherit;padding:12px;margin:8px 0 18px;border:1px solid #357077;border-radius:12px}button{background:#63e5d6;color:#082c31;border:0}label{display:block}small{color:#9ec6c8}</style><h1>Welcome to Deskter</h1><p>Choose your 2.4 GHz Wi-Fi network.</p><button type="button" id="scan">Scan networks</button><p id="message" role="status">Finding nearby networks...</p><label>Nearby Wi-Fi<select id="networks"><option value="">Select a network</option></select></label><form method="post" action="/wifi"><label>Wi-Fi name<input id="ssid" name="ssid" maxlength="32" required autocomplete="off"></label><label>Password<input name="password" type="password" maxlength="64" autocomplete="off"></label><button>Connect Deskter</button></form><small>For a hidden network, type its name. Leave the password empty for an open network. Your password stays on Deskter.</small><script>
const list=document.getElementById('networks'),msg=document.getElementById('message'),btn=document.getElementById('scan');
list.onchange=()=>{document.getElementById('ssid').value=list.value;};
let busy=false;
async function scan(fresh=false){if(busy)return;busy=true;btn.disabled=true;msg.textContent='Scanning...';try{const r=await fetch('/scan'+(fresh?'?refresh=1':''),{cache:'no-store'});if(r.status===202){busy=false;setTimeout(()=>scan(),1200);return;}if(!r.ok)throw Error();const data=await r.json();list.replaceChildren(new Option('Select a network',''));const seen=new Set();data.networks.sort((a,b)=>b.rssi-a.rssi).forEach(n=>{if(!n.ssid||seen.has(n.ssid))return;seen.add(n.ssid);list.add(new Option(n.ssid+' ('+n.rssi+' dBm'+(n.secure?', secured':', open')+')',n.ssid));});msg.textContent=seen.size+' networks found';}catch(e){msg.textContent='Scan failed. Try again or enter the network name.';}busy=false;btn.disabled=false;}
btn.onclick=()=>scan(true);scan();</script></html>)HTML");
    });
    portal.on("/scan",HTTP_GET,[] {
        portal.sendHeader("Cache-Control","no-store");
        int count=WiFi.scanComplete();
        if(count==WIFI_SCAN_RUNNING) {portal.send(202,"application/json","{\"scanning\":true}");return;}
        if((portal.hasArg("refresh") || !scanFinishedAt || millis()-scanFinishedAt>30000) && !scanPending) {
            WiFi.scanDelete();scanFinishedAt=0;
            const int result=WiFi.scanNetworks(true,false);
            scanPending=result==WIFI_SCAN_RUNNING;
            if(!scanPending && result<0) {portal.send(503,"application/json","{\"error\":\"scan failed\"}");return;}
            portal.send(202,"application/json","{\"scanning\":true}");return;
        }
        if(count<0) {scanPending=false;portal.send(503,"application/json","{\"error\":\"scan failed\"}");return;}
        scanPending=false;scanFinishedAt=millis();
        JsonDocument result;auto networks=result["networks"].to<JsonArray>();
        for(int i=0;i<count && i<30;++i) {auto n=networks.add<JsonObject>();n["ssid"]=WiFi.SSID(i);n["rssi"]=WiFi.RSSI(i);n["secure"]=WiFi.encryptionType(i)!=WIFI_AUTH_OPEN;}
        String json;serializeJson(result,json);portal.send(200,"application/json",json);
    });
    portal.on("/wifi",HTTP_POST,[] {
        String name=portal.arg("ssid"),password=portal.arg("password");
        if (name.isEmpty() || name.length()>32 || password.length()>64 || (!password.isEmpty() && password.length()<8)) {
            portal.send(400,"text/plain","Check the Wi-Fi name and password length."); return;
        }
        wifiSsid=name; wifiPassword=password;
        manualPortalUntil=0;
        preferences.putString("ssid",wifiSsid); preferences.putString("pass",wifiPassword);
        newWifi=true;
        portal.send(200,"text/html","<meta name='viewport' content='width=device-width,initial-scale=1'><h2>Connecting Deskter</h2><p>Check its display. You can return your phone to your usual Wi-Fi.</p>");
    });
    portal.onNotFound([] { portal.sendHeader("Location","http://192.168.4.1/"); portal.send(302,"text/plain",""); });
    portal.begin(); portalActive=true;
    status("Deskter Setup / deskter123 / 192.168.4.1");
    Serial.println("VOICE setup Wi-Fi: Deskter Setup; setup password: deskter123; open http://192.168.4.1/");
}

void connectWifi() {
    if(wifiStarted) WiFi.disconnect(false,false);
    WiFi.begin(wifiSsid.c_str(),wifiPassword.c_str()); wifiStarted=millis();
    lastWifiRetry=wifiStarted;
    ready=false; activating=false; nextConfig=0;
    if(!portalActive) session::setVisual(session::Visual::Connecting);
    status("Connecting to your Wi-Fi...");
    Serial.println("VOICE connecting to saved Wi-Fi (credentials hidden)");
}

int post(const char *suffix,const String &body,JsonDocument *result) {
    session::HeavyWork memoryLease; // Avoid overlapping TLS handshake and face scratch peaks.
    NetworkClientSecure tls;
    if(serverCa.isEmpty()) tls.setCACertBundle(deskterCaStart,size_t(deskterCaEnd-deskterCaStart));
    else tls.setCACert(serverCa.c_str());
    tls.setHandshakeTimeout(10);
    HTTPClient http; http.setTimeout(12000); http.setConnectTimeout(10000); http.setReuse(false);
    if (!http.begin(tls,otaEndpoint+suffix)) return -1;
    http.addHeader("Device-Id",deviceId); http.addHeader("Client-Id",uuid);
    http.addHeader("Activation-Version","1"); http.addHeader("Accept-Language","en-US");
    http.addHeader("User-Agent",String(boardName)+"/"+firmwareVersion);
    http.addHeader("Content-Type","application/json");
    if(!serverAuth.isEmpty()) http.addHeader("Authorization","Bearer "+serverAuth);
    const int response=http.POST(body);
    if (response==200 && result) {
        String data=http.getString();
        if (data.length()>16384 || deserializeJson(*result,data)) { http.end(); return -2; }
    }
    http.end(); return response;
}

void configureCloud() {
    if (activating) {
        const int response=post("activate","{}",nullptr);
        Serial.printf("VOICE activation HTTP=%d\n",response);
        if (response==200) { activating=false; activationCode=""; nextConfig=millis()+1000; }
        else if (++activationAttempts>=10) { activating=false; nextConfig=millis()+3000; }
        else nextConfig=millis()+5000;
        return;
    }
    JsonDocument request;
    request["version"]=2; request["language"]="en-US";
    request["flash_size"]=ESP.getFlashChipSize(); request["minimum_free_heap_size"]=String(ESP.getMinFreeHeap());
    request["mac_address"]=deviceId; request["uuid"]=uuid; request["chip_model_name"]="esp32s3";
    esp_chip_info_t chip{}; esp_chip_info(&chip);
    auto info=request["chip_info"].to<JsonObject>();
    info["model"]=int(chip.model); info["cores"]=chip.cores; info["revision"]=chip.revision; info["features"]=chip.features;
    auto application=request["application"].to<JsonObject>();
    application["name"]="deskter-arduino"; application["version"]=firmwareVersion;
    application["compile_time"]=String(__DATE__)+"T"+__TIME__;
    const auto *description=esp_app_get_description(); application["idf_version"]=description->idf_ver;
    char hash[65]; for(unsigned i=0;i<32;++i) snprintf(hash+2*i,3,"%02x",description->app_elf_sha256[i]);
    application["elf_sha256"]=hash;
    auto parts=request["partition_table"].to<JsonArray>();
    auto iterator=esp_partition_find(ESP_PARTITION_TYPE_ANY,ESP_PARTITION_SUBTYPE_ANY,nullptr);
    while(iterator) {
        const auto *partition=esp_partition_get(iterator); auto row=parts.add<JsonObject>();
        row["label"]=partition->label; row["type"]=int(partition->type); row["subtype"]=int(partition->subtype);
        row["address"]=partition->address; row["size"]=partition->size;
        iterator=esp_partition_next(iterator);
    }
    const auto *running=esp_ota_get_running_partition(); request["ota"]["label"]=running ? running->label : "app0";
    request["display"]["width"]=320; request["display"]["height"]=240; request["display"]["monochrome"]=false;
    auto board=request["board"].to<JsonObject>();
    board["type"]=boardName; board["name"]=boardName; board["manufacturer"]="Seeed Studio";
    board["mac"]=deviceId;
    request["protocol"]["features"]["mcp"]=false; request["protocol"]["features"]["aec"]=false;
    String body; serializeJson(request,body); request.clear();
    JsonDocument result;
    const int response=post("",body,&result);
    Serial.printf("VOICE configuration HTTP=%d\n",response);
    nextConfig=millis()+15000;
    if(response!=200) { status("Xiaozhi setup retry; check internet"); return; }
    if(!serverCa.isEmpty()) {
        const uint64_t stamp=result["server_time"]["timestamp"] | uint64_t(0);
        if(stamp>=1700000000000ULL) {
            const uint64_t seconds=stamp/1000;
            timeval clock{}; clock.tv_sec=seconds; settimeofday(&clock,nullptr);
            if(seconds>preferences.getULong64("clock",0)+3600) preferences.putULong64("clock",seconds);
        }
    }
    // Report response shape, never transport passwords/tokens or the whole body.
    Serial.print("VOICE configuration sections:");
    for(JsonPair field:result.as<JsonObject>()) Serial.printf(" %s",field.key().c_str());
    Serial.println();
    activationCode="";
    const JsonVariant code=result["activation"]["code"];
    if(code.is<const char *>()) activationCode=code.as<String>();
    else if(code.is<unsigned long>() && code.as<unsigned long>()<=999999) {
        char digits[7]; snprintf(digits,sizeof(digits),"%06lu",code.as<unsigned long>()); activationCode=digits;
    }
    const String challenge=result["activation"]["challenge"] | "";
    Serial.printf("VOICE binding response: activation=%u code=%u challenge=%u\n",
        unsigned(result["activation"].is<JsonObject>()),unsigned(!activationCode.isEmpty()),unsigned(!challenge.isEmpty()));
    const String activationMessage=result["activation"]["message"] | "";
    if(!activationMessage.isEmpty()) Serial.printf("VOICE service activation message: %.500s\n",activationMessage.c_str());
    if (!activationCode.isEmpty() || !challenge.isEmpty()) {
        activating=true; activationAttempts=0;
        String line="xiaozhi.me / activation "+activationCode; status(line.c_str());
        Serial.printf("VOICE bind at xiaozhi.me; activation code: %s\n",activationCode.c_str());
        nextConfig=millis()+3000; return;
    }
    wsUrl=result["websocket"]["url"] | ""; wsToken=result["websocket"]["token"] | "";
    protocolVersion=result["websocket"]["version"] | 1;
    if (protocolVersion<1 || protocolVersion>3) { status("Unsupported Xiaozhi audio version"); return; }
    if (!wsUrl.startsWith("wss://")) { status("Xiaozhi gave no secure WebSocket URL"); return; }
    ready=true; session::setVisual(session::Visual::Idle); status("Say Hey Deskter / server ready"); Serial.println("VOICE cloud settings ready (token hidden)");
    // Firmware/asset URLs are intentionally unused: retain this Arduino hardware build.
}

void sendListening() {
    if (!helloReady) return;
    inputBytes=0; wakeaudio::discardPcm(); opus_encoder_ctl(encoder,OPUS_RESET_STATE);
    JsonDocument message; message["session_id"]=sessionId; message["type"]="listen";
    message["state"]="start"; message["mode"]="auto";
    String text; serializeJson(message,text); socketClient.sendTXT(text);
    session::setVisual(session::Visual::Listening);status("Listening...");
}

uint16_t read16(const uint8_t *p) { return (uint16_t(p[0])<<8)|p[1]; }
uint32_t read32(const uint8_t *p) { return (uint32_t(p[0])<<24)|(uint32_t(p[1])<<16)|(uint32_t(p[2])<<8)|p[3]; }

void socketEvent(WStype_t type,uint8_t *data,size_t length) {
    if (type==WStype_CONNECTED) {
        JsonDocument hello; hello["type"]="hello"; hello["version"]=protocolVersion;
        hello["transport"]="websocket"; hello["features"]["mcp"]=false; hello["features"]["aec"]=false;
        auto audio=hello["audio_params"].to<JsonObject>(); audio["format"]="opus";
        audio["sample_rate"]=16000; audio["channels"]=1; audio["frame_duration"]=60;
        String text; serializeJson(hello,text); const bool sent=socketClient.sendTXT(text); helloStarted=millis();
        Serial.printf("VOICE WebSocket connected; hello sent=%u version=%u\n",unsigned(sent),protocolVersion);
    } else if (type==WStype_DISCONNECTED) {
        ++playbackEpoch;playbackFinished.store(true);
        helloReady=false; ttsEnding=false; wakeaudio::setSpeaking(false); inputBytes=0;
        session::setVisual(session::Visual::Connecting);status("Voice disconnected; reconnecting if awake"); Serial.println("VOICE WebSocket disconnected");
    } else if (type==WStype_TEXT) {
        if(length>16384) { ++audioErrors; return; }
        JsonDocument message; if(deserializeJson(message,data,length)) return;
        const String kind=message["type"] | "";
        if(kind=="hello" || kind=="alert" || kind=="error") Serial.printf("VOICE server event: %.24s\n",kind.c_str());
        if(kind=="hello") {
            const String transport=message["transport"] | "", format=message["audio_params"]["format"] | "opus";
            if(transport!="websocket" || format!="opus" || (message["audio_params"]["channels"] | 1)!=1) {
                status("Unsupported server audio format"); return;
            }
            sessionId=message["session_id"] | ""; helloReady=true; session::touch(); sendListening();
            Serial.println("VOICE server hello accepted; live microphone streaming enabled");
        } else if(kind=="tts") {
            const String state=message["state"] | "";
            session::touch();
            if(state=="start") {
                ++playbackEpoch;playbackLastWrite.store(0);playbackFinished.store(false);
                wakeaudio::setSpeaking(true);ttsEnding=false;inputBytes=0;session::setVisual(session::Visual::Thinking);status("Preparing speech...");
            }
            else if(state=="stop") { playbackFinished.store(true);ttsEnding=true;ttsEnded=millis(); }
            else if(state=="preparing" && !wakeaudio::speaking()) { session::touch();session::setVisual(session::Visual::Thinking); }
        } else if(kind=="device") {
            const String action=message["action"] | "";
            if(action=="camera_open") cameramode::request(true);
            else if(action=="camera_close") cameramode::request(false);
        } else if(kind=="stt") {
            session::touch(); session::setVisual(session::Visual::Thinking); status("Heard you / thinking..."); Serial.println("VOICE real server transcription received (text not logged)");
        } else if(kind=="alert" || kind=="error") {
            const String text=message["message"] | "Voice service alert"; session::setVisual(session::Visual::Error);status(text.c_str());
        }
    } else if(type==WStype_BIN && helloReady && session::active() && wakeaudio::speaking()) {
        if(protocolVersion==2) {
            if(length<16 || read16(data)!=2 || read16(data+2)!=0 || read32(data+12)!=length-16) { ++audioErrors; return; }
            data+=16; length-=16;
        } else if(protocolVersion==3) {
            if(length<4 || data[0]!=0 || read16(data+2)!=length-4) { ++audioErrors; return; }
            data+=4; length-=4;
        }
        if(!length || length>1500) { ++audioErrors; return; }
        PlaybackPacket packet{};packet.epoch=playbackEpoch.load();packet.length=length;
        memcpy(packet.bytes,data,length);
        if(xQueueSend(playbackQueue,&packet,0)!=pdTRUE) ++playbackDrops;
        session::touch();
    }
}

void openSocket() {
    const int pathStart=wsUrl.indexOf('/',6);
    String authority=pathStart<0 ? wsUrl.substring(6) : wsUrl.substring(6,pathStart);
    String path=pathStart<0 ? "/" : wsUrl.substring(pathStart);
    uint16_t port=443; const int colon=authority.lastIndexOf(':');
    if(colon>=0) { port=authority.substring(colon+1).toInt(); authority=authority.substring(0,colon); }
    if(authority.isEmpty() || !port) { status("Invalid Xiaozhi address"); ready=false; return; }
    // WebSockets adds CRLF after extraHeaders, then its own User-Agent header.
    // A trailing CRLF here creates a premature blank line and sends that
    // remaining HTTP header as invalid bytes in the upgraded WebSocket stream.
    wsHeaders="Device-Id: "+deviceId+"\r\nClient-Id: "+uuid+"\r\nProtocol-Version: "+String(protocolVersion);
    if(!wsToken.isEmpty()) wsHeaders+="\r\nAuthorization: "+(wsToken.indexOf(' ')<0 ? String("Bearer ")+wsToken : wsToken);
    if(serverCa.isEmpty()) socketClient.beginSslWithBundle(authority.c_str(),port,path.c_str(),deskterCaStart,size_t(deskterCaEnd-deskterCaStart),"");
    else socketClient.beginSslWithCA(authority.c_str(),port,path.c_str(),serverCa.c_str(),"");
    socketClient.setExtraHeaders(wsHeaders.c_str());
    wsStarted=true; helloReady=false; helloStarted=millis();
    session::setVisual(session::Visual::Connecting);status("Connecting voice...");
}

void transmitAudio() {
    auto *bytes=reinterpret_cast<uint8_t *>(inputPcm);
    inputBytes+=wakeaudio::readPcm(bytes+inputBytes,1920-inputBytes);
    if(inputBytes<1920) return;
    const int offset=protocolVersion==2 ? 16 : protocolVersion==3 ? 4 : 0;
    const int count=opus_encode(encoder,inputPcm,960,encoded+offset,400);
    inputBytes=0;
    if(count<=0) { ++audioErrors; return; }
    if(protocolVersion==2) {
        memset(encoded,0,16); encoded[1]=2;
        const uint32_t timestamp=millis();
        for(unsigned i=0;i<4;++i) { encoded[8+i]=timestamp>>(24-8*i); encoded[12+i]=uint32_t(count)>>(24-8*i); }
    } else if(protocolVersion==3) { encoded[0]=encoded[1]=0; encoded[2]=count>>8; encoded[3]=count; }
    if(socketClient.sendBIN(encoded,count+offset)) ++audioSent; else ++audioErrors;
}

bool syncLocalClock() {
    WiFiUDP udp;
    IPAddress host;
    if(!host.fromString(serverNtp) || !udp.begin(0)) return false;
    uint8_t packet[48]{}; packet[0]=0x23;
    uint8_t nonce[8]; esp_fill_random(nonce,sizeof(nonce));
    memcpy(packet+40,nonce,8);
    udp.beginPacket(host,8123); udp.write(packet,sizeof(packet));
    if(!udp.endPacket()) return false;
    const uint32_t started=millis();
    while(millis()-started<1200) {
        if(udp.parsePacket()>=48 && udp.remoteIP()==host && udp.remotePort()==8123) {
            if(udp.read(packet,sizeof(packet))!=48 || (packet[0]&7)!=4 ||
               (packet[0]>>6)==3 || memcmp(packet+24,nonce,8)) return false;
            uint64_t seconds=0;
            for(unsigned i=40;i<44;++i) seconds=(seconds<<8)|packet[i];
            if(seconds<2208988800ULL) seconds+=4294967296ULL;
            seconds-=2208988800ULL;
            if(seconds<1700000000ULL) return false;
            timeval clock{}; clock.tv_sec=seconds; settimeofday(&clock,nullptr);
            preferences.putULong64("clock",seconds);
            Serial.println("VOICE offline LAN clock synchronized");
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    return false;
}

bool processServerConfig() {
    ServerRequest request{};
    if(xQueueReceive(serverRequests,&request,0)!=pdTRUE) return false;
    esp_sntp_stop();
    if(wsStarted) socketClient.disconnect();
    wsStarted=helloReady=ready=activating=ttsEnding=false;
    wakeaudio::setSpeaking(false); session::sleep(); inputBytes=0; wakeaudio::discardPcm();
    if(request.restore) {
        for(const char *key:{"otaurl","serverca","serverauth","serverntp"}) preferences.remove(key);
        otaEndpoint=otaUrl; serverCa=""; serverAuth=""; serverNtp="";
        Serial.println("VOICE official service restored; Wi-Fi and client UUID preserved");
    } else {
        otaEndpoint=request.url; serverCa=request.ca; serverAuth=request.token; serverNtp=request.ntp;
        if(!otaEndpoint.endsWith("/")) otaEndpoint+="/";
        preferences.putString("otaurl",otaEndpoint); preferences.putString("serverca",serverCa);
        preferences.putString("serverauth",serverAuth); preferences.putString("serverntp",serverNtp);
        if(request.utc>=1700000000ULL) {
            timeval clock{}; clock.tv_sec=request.utc; settimeofday(&clock,nullptr);
            preferences.putULong64("clock",request.utc);
        }
        Serial.println("VOICE selected server settings saved (verified TLS; token hidden)");
    }
    memset(&request,0,sizeof(request)); nextConfig=0; status("Connecting to selected voice server...");
    return true;
}

void bootChime() {
    wakeaudio::setSpeaking(true);
    constexpr float notes[]={523.25f,659.25f,783.99f,1046.50f};
    int16_t pcm[240];
    for(float note:notes) {
        constexpr int samples=3360;
        for(int offset=0;offset<samples;offset+=240) {
            for(int i=0;i<240;++i) {
                const float phase=float(offset+i)/samples;
                const float envelope=std::min(1.f,phase*12.f)*std::pow(1.f-phase,1.8f);
                pcm[i]=int16_t(6500.f*envelope*std::sin(6.2831853f*note*(offset+i)/24000.f));
            }
            speaker.write(reinterpret_cast<uint8_t *>(pcm),sizeof(pcm));
        }
    }
    delay(80);wakeaudio::setSpeaking(false);wakeaudio::discardPcm();
    Serial.println("VOICE boot chime complete");
}

void networkTask(void *) {
    bootChime();
    // Exercise the actual codec on non-played synthetic PCM to check the MCU
    // codec path and stack before networking; this is not a conversation test.
    bool codecValid=true;
    for(unsigned frame=0;frame<8;++frame) {
        for(unsigned i=0;i<960;++i) inputPcm[i]=frame<2 ? 0 : int16_t(((i*257+frame*701)%16000)-8000);
        const int count=opus_encode(encoder,inputPcm,960,encoded,400);
        if(count<=0 || opus_decode(decoder,encoded,count,outputPcm,2880,0)!=1440) { codecValid=false; break; }
    }
    if(!codecValid) { status("Voice codec self-check failed"); Serial.println("VOICE codec check FAILED"); vTaskDelete(nullptr); }
    opus_encoder_ctl(encoder,OPUS_RESET_STATE); opus_decoder_ctl(decoder,OPUS_RESET_STATE);
    Serial.printf("VOICE codec self-check passed (not played); stack_free=%u\n",unsigned(uxTaskGetStackHighWaterMark(nullptr)));
    // Arduino's OPI PSRAM SDK explicitly allows external task stacks. This
    // task performs no NVS/flash writes, keeping TLS's scarce internal RAM free.
    if(xTaskCreatePinnedToCoreWithCaps(playbackTask,"speaker_play",32768,nullptr,3,&playbackHandle,1,
                                     MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS) {
        status("Speaker playback task failed");Serial.println("VOICE playback task allocation FAILED");
        vTaskDelete(nullptr);
    }
    Serial.printf("VOICE playback queue=%u frames prefill=%u frames separate PSRAM-stack task\n",
                  playbackQueueFrames,playbackPrefillFrames);
    preferences.begin("deskter",false); makeUuid();
    otaEndpoint=preferences.getString("otaurl",otaUrl); serverCa=preferences.getString("serverca","");
    serverAuth=preferences.getString("serverauth",""); serverNtp=preferences.getString("serverntp","");
    if(!serverCa.isEmpty()) {
        const uint64_t saved=preferences.getULong64("clock",0);
        if(saved>=1700000000ULL) { timeval clock{}; clock.tv_sec=saved; settimeofday(&clock,nullptr); }
        Serial.println("VOICE using saved local server and pinned TLS CA");
    }
    wifiSsid=preferences.getString("ssid",""); wifiPassword=preferences.getString("pass","");
    WiFi.persistent(false); WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true);
    // Match official SystemInfo::GetMacAddress: read the real STA hardware MAC
    // and serialize lowercase, consistently in OTA, activation and WebSocket.
    uint8_t mac[6]{};
    if(esp_read_mac(mac,ESP_MAC_WIFI_STA)!=ESP_OK) {
        status("Cannot read device MAC"); Serial.println("VOICE hardware identity FAILED");
        for(;;) vTaskDelay(pdMS_TO_TICKS(1000));
    }
    char macText[18];
    snprintf(macText,sizeof(macText),"%02x:%02x:%02x:%02x:%02x:%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    deviceId=macText;
    Serial.printf("VOICE device identity: MAC=%s Client-Id=%s\n",deviceId.c_str(),uuid.c_str());
    WiFi.onEvent([](WiFiEvent_t,WiFiEventInfo_t info) {
        wifiDisconnectReason.store(info.wifi_sta_disconnected.reason);
    },ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    socketClient.onEvent(socketEvent); socketClient.setReconnectInterval(5000);
    if(wifiSsid.isEmpty()) startPortal(); else connectWifi();
    bool clockStarted=false;
    uint32_t nextLocalClock=0;
    for(;;) {
        if(processServerConfig()) { clockStarted=false; nextLocalClock=0; }
        const int portalCommand=portalControl.exchange(0);
        if(portalCommand>0) {session::sleep();manualPortalUntil=millis()+300000;startPortal();}
        else if(portalCommand<0) manualPortalUntil=0;
        WifiRequest request{};
        if(xQueueReceive(wifiRequests,&request,0)==pdTRUE) {
            const bool changed=wifiSsid!=request.ssid || wifiPassword!=request.password;
            wifiSsid=request.ssid; wifiPassword=request.password; memset(&request,0,sizeof(request));
            preferences.putString("ssid",wifiSsid); preferences.putString("pass",wifiPassword);
            newWifi=changed || (!wifiStarted && WiFi.status()!=WL_CONNECTED);
            Serial.println("USB Wi-Fi settings saved (secrets hidden)");
        }
        if(portalActive) { dns.processNextRequest(); portal.handleClient(); }
        if(newWifi) { newWifi=false; connectWifi(); }
        const int reason=wifiDisconnectReason.exchange(0);
        if(reason) Serial.printf("VOICE Wi-Fi disconnected; reason=%d (201=no AP, 202=authentication failure, 15=handshake timeout)\n",reason);
        if(WiFi.status()!=WL_CONNECTED) {
            wifiWasConnected=false;
            if(wsStarted) { socketClient.disconnect(); wsStarted=false; helloReady=false; }
            wakeaudio::setSpeaking(false); ttsEnding=false; inputBytes=0;
            session::setVisual(portalActive ? session::Visual::Setup : session::Visual::Connecting);
            if(!portalActive && wifiStarted && millis()-wifiStarted>25000) {
                startPortal();

            }
            if(!wifiSsid.isEmpty() && WiFi.scanComplete()!=WIFI_SCAN_RUNNING && millis()-lastWifiRetry>30000) {
                lastWifiRetry=millis(); WiFi.reconnect();
                Serial.println("VOICE retrying saved Wi-Fi");
            }
            wakeaudio::discardPcm(); vTaskDelay(pdMS_TO_TICKS(10)); continue;
        }
        if(!wifiWasConnected) {
            wifiWasConnected=true;
            Serial.printf("VOICE Wi-Fi connected; channel=%d RSSI=%d dBm; IP=%s\n",WiFi.channel(),WiFi.RSSI(),WiFi.localIP().toString().c_str());
        }
        if(portalActive && (!manualPortalUntil || int32_t(millis()-manualPortalUntil)>=0)) { portal.stop(); dns.stop(); WiFi.softAPdisconnect(true); WiFi.mode(WIFI_STA); portalActive=false; WiFi.scanDelete();scanPending=false;scanFinishedAt=0;session::setVisual(session::Visual::Connecting); }
        if(!clockStarted) {
            if(serverNtp.isEmpty()) configTime(0,0,"pool.ntp.org","time.cloudflare.com");
            else esp_sntp_stop();
            clockStarted=true; status("Setting voice server clock...");
        }
        if(!serverNtp.isEmpty() && !session::active() && int32_t(millis()-nextLocalClock)>=0) {
            const bool synced=syncLocalClock();
            nextLocalClock=millis()+(synced ? 1800000UL : 30000UL);
        }
        if(time(nullptr)<1700000000) { wakeaudio::discardPcm(); vTaskDelay(pdMS_TO_TICKS(50)); continue; }
        if(!ready && int32_t(millis()-nextConfig)>=0) configureCloud();
        if(session::active() && ready) {
            if(!wsStarted) openSocket();
            if(wsStarted) {
                if(!helloReady || !socketClient.isConnected()) { session::HeavyWork memoryLease; socketClient.loop(); }
                else socketClient.loop();
            }
            if(helloReady && ttsEnding && millis()-ttsEnded>=200 &&
               uxQueueMessagesWaiting(playbackQueue)==0 && !playbackBusy.load() &&
               (!playbackLastWrite.load() || millis()-playbackLastWrite.load()>=150)) {
                ttsEnding=false; wakeaudio::setSpeaking(false); sendListening();
            }
            if(helloReady && !wakeaudio::speaking()) transmitAudio(); else wakeaudio::discardPcm();
            if(wsStarted && !helloReady && millis()-helloStarted>20000) {
                socketClient.disconnect(); wsStarted=false; ready=false; nextConfig=millis()+5000;
            }
        } else {
            if(wsStarted) { socketClient.disconnect(); wsStarted=false; helloReady=false; wakeaudio::setSpeaking(false); }
            wakeaudio::discardPcm(); inputBytes=0;
            if(ready && !portalActive && session::visual()!=session::Visual::Error) session::setVisual(session::Visual::Idle);
        }
        if(millis()-lastReport>=5000) {
            Serial.printf("VOICE wifi=%u ready=%u active=%u hello=%u tx=%lu rx=%lu errors=%lu stack_free=%u\n",
                unsigned(WiFi.status()==WL_CONNECTED),unsigned(ready),unsigned(session::active()),unsigned(helloReady),
                (unsigned long)audioSent,(unsigned long)audioReceived,(unsigned long)audioErrors,
                unsigned(uxTaskGetStackHighWaterMark(nullptr)));
            lastReport=millis();
            Serial.printf("PLAYBACK queued=%u drops=%lu underruns=%lu busy=%u stack_free=%u\n",
                unsigned(uxQueueMessagesWaiting(playbackQueue)),(unsigned long)playbackDrops.load(),
                (unsigned long)playbackUnderruns.load(),unsigned(playbackBusy.load()),
                playbackHandle ? unsigned(uxTaskGetStackHighWaterMark(playbackHandle)) : 0);
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
}

namespace voice {
void pollSerial() {
    static char line[2560]{};
    static unsigned used=0;
    static bool overflow=false;
    while(Serial.available()) {
        const char c=Serial.read();
        if(c=='\r') continue;
        if(c!='\n') {
            if(used<sizeof(line)-1) line[used++]=c; else overflow=true;
            continue;
        }
        if(used && !overflow) {
            line[used]=0; JsonDocument command;
            const bool parsed=!deserializeJson(command,line);
            if(parsed && command["cmd"]=="server") {
                ServerRequest request{};
                request.restore=command["reset"] | false;
                const String url=command["url"] | "",ca=command["ca"] | "",token=command["token"] | "",ntp=command["ntp"] | "";
                const bool publicTls=command["public"] | false;
                const bool valid=url.startsWith("https://") && url.length()<sizeof(request.url) && url.indexOf('\n')<0 && url.indexOf('\r')<0 &&
                    ((publicTls && ca.isEmpty()) || (!publicTls && ca.startsWith("-----BEGIN CERTIFICATE-----"))) && ca.length()<sizeof(request.ca) &&
                    token.length()>20 && token.length()<sizeof(request.token) && token.indexOf('\r')<0 && token.indexOf('\n')<0 &&
                    ((publicTls && ntp.isEmpty()) || (!publicTls && ntp.length()>0)) && ntp.length()<sizeof(request.ntp);
                if(request.restore || valid) {
                    url.toCharArray(request.url,sizeof(request.url)); ca.toCharArray(request.ca,sizeof(request.ca));
                    token.toCharArray(request.token,sizeof(request.token)); ntp.toCharArray(request.ntp,sizeof(request.ntp));
                    request.utc=command["utc"] | uint64_t(0);
                    if(serverRequests) xQueueOverwrite(serverRequests,&request);
                } else Serial.println("USB server configuration rejected; check URL, CA, token and clock host");
                memset(&request,0,sizeof(request));
            } else if(parsed && command["cmd"]=="setup") {
                portalControl.store((command["enabled"] | true) ? 1 : -1);
            } else if(parsed && command["cmd"]=="info") {
                Serial.printf("DEVICE station_ip=%s camera=%u\n",WiFi.localIP().toString().c_str(),unsigned(cameramode::requested()));
            } else if(parsed && command["cmd"]=="camera" && command["enabled"].is<bool>()) {
                cameramode::request(command["enabled"].as<bool>());
            } else if(parsed && command["cmd"]=="wifi") {
                const String ssid=command["ssid"] | "",password=command["password"] | "";
                if(!ssid.isEmpty() && ssid.length()<=32 && password.length()<=64 && (password.isEmpty() || password.length()>=8)) {
                    WifiRequest request{};
                    ssid.toCharArray(request.ssid,sizeof(request.ssid)); password.toCharArray(request.password,sizeof(request.password));
                    if(wifiRequests) xQueueOverwrite(wifiRequests,&request);
                    memset(&request,0,sizeof(request));
                } else Serial.println("USB Wi-Fi configuration rejected; check field lengths");
            }
        }
        memset(line,0,sizeof(line)); used=0; overflow=false;
    }
}
bool begin() {
    int error=0;
    encoder=opus_encoder_create(16000,1,OPUS_APPLICATION_VOIP,&error);
    if(!encoder || error!=OPUS_OK) return false;
    opus_encoder_ctl(encoder,OPUS_SET_BITRATE(16000)); opus_encoder_ctl(encoder,OPUS_SET_COMPLEXITY(0));
    decoder=opus_decoder_create(24000,1,&error);
    if(!decoder || error!=OPUS_OK) return false;
    inputPcm=static_cast<int16_t *>(heap_caps_malloc(1920,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    outputPcm=static_cast<int16_t *>(heap_caps_malloc(5760,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    encoded=static_cast<uint8_t *>(heap_caps_malloc(416,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!inputPcm || !outputPcm || !encoded) return false;
    speaker.setPins(43,44,6); speaker.setTimeout(1000);
    if(!speaker.begin(I2S_MODE_STD,24000,I2S_DATA_BIT_WIDTH_16BIT,I2S_SLOT_MODE_MONO)) return false;
    Serial.println("VOICE speaker digital volume=100% (no attenuation)");
    // libopus uses alloca; leave ample internal stack for codec + TLS call paths.
    wifiRequests=xQueueCreate(1,sizeof(WifiRequest));
    auto *storage=static_cast<uint8_t *>(heap_caps_malloc(sizeof(ServerRequest),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(storage) serverRequests=xQueueCreateStatic(1,sizeof(ServerRequest),storage,&serverQueueControl);
    auto *audioStorage=static_cast<uint8_t *>(heap_caps_malloc(playbackQueueFrames*sizeof(PlaybackPacket),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(audioStorage) playbackQueue=xQueueCreateStatic(playbackQueueFrames,sizeof(PlaybackPacket),audioStorage,&playbackQueueControl);
    return wifiRequests && serverRequests && playbackQueue && xTaskCreatePinnedToCore(networkTask,"xiaozhi_voice",32768,nullptr,2,&networkHandle,1)==pdPASS;
}
float speakerLevel() {
    const uint32_t last=playbackLastWrite.load();
    return wakeaudio::speaking() && last && millis()-last<160 ? outputLevel.load() : 0.f;
}
unsigned stackFree() { return networkHandle ? uxTaskGetStackHighWaterMark(networkHandle) : 0; }
}
