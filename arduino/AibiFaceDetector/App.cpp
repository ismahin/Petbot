#include <Arduino.h>
#include <cmath>
#include <algorithm>
#include "esp_system.h"
#include "App.hpp"
#include "Tft.hpp"
#include "Session.hpp"
#include "WakeAudio.hpp"
#include "Voice.hpp"

SET_LOOP_TASK_STACK_SIZE(8192);
#if !CONFIG_IDF_TARGET_ESP32S3 || !defined(BOARD_HAS_PSRAM)
#error "Select XIAO ESP32S3 with OPI PSRAM enabled."
#endif
namespace {
PetDisplay lcd;
lgfx::LGFX_Sprite frame(&lcd);
bool screenReady=false;
float gazeX=0,gazeY=0,openness=0,level=0;
uint32_t nextBlink=2800,blinkAt=0,nextGaze=0;
float targetX=0,targetY=0;
const char *label(session::Visual state) {
    using V=session::Visual;
    switch(state) {
        case V::Boot:return "HELLO, I'M DESKTER";
        case V::Idle:return "Say Hey Deskter";
        case V::Connecting:return "CONNECTING";
        case V::Setup:return "WI-FI SETUP";
        case V::Listening:return "I'M LISTENING";
        case V::Thinking:return "THINKING";
        case V::Speaking:return "LET'S TALK";
        default:return "LET'S TRY AGAIN";
    }
}
void drawFace() {
    using V=session::Visual;
    const uint32_t now=millis();const float t=now/1000.f;
    V state=session::visual();
    if(state==V::Idle && session::active()) state=V::Connecting;
    if((state==V::Listening || state==V::Thinking || state==V::Speaking) && !session::active()) state=V::Idle;
    if(now>=nextGaze) {
        nextGaze=now+1800+esp_random()%2800;
        targetX=int(esp_random()%17)-8;targetY=int(esp_random()%9)-4;
    }
    const float aimX=state==V::Thinking ? 12.f : state==V::Listening ? 0.f : targetX;
    const float aimY=state==V::Thinking ? -10.f : state==V::Listening ? -2.f : targetY;
    gazeX+=(aimX-gazeX)*.10f;gazeY+=(aimY-gazeY)*.10f;
    if(now>=nextBlink && !blinkAt) {blinkAt=now;nextBlink=now+2500+esp_random()%4300;}
    float blink=1.f;
    if(blinkAt) {const uint32_t dt=now-blinkAt;if(dt>=170) blinkAt=0;else blink=std::max(.06f,std::abs(float(dt)-85.f)/85.f);}
    openness+=(1.f-openness)*.10f;
    const float desired=voice::speakerLevel();level+=(desired-level)*(desired>level ? .45f : .16f);
    const bool talking=state==V::Speaking;
    const uint16_t bright=state==V::Error ? lcd.color565(255,150,65) : state==V::Setup ? lcd.color565(90,180,255) : lcd.color565(80,240,235);
    const uint16_t glow=lcd.color565(8,35,44),dim=lcd.color565(25,100,110);
    frame.fillScreen(TFT_BLACK);
    const float breath=std::sin(t*2.5f)*2.f;
    for(int eye=0;eye<2;++eye) {
        int x=eye ? 184 : 48;
        int w=88,h=int((state==V::Listening ? 82 : state==V::Thinking ? 63 : 74)*blink*openness);
        h=std::max(4,h);int y=105-h/2+int(gazeY+breath);
        if(talking) y-=int(level*3);
        x+=int(gazeX);
        frame.fillRoundRect(x-4,y-4,w+8,h+8,std::min(27,(h+8)/2),glow);
        frame.fillRoundRect(x,y,w,h,std::min(23,h/2),bright);
        if(h>28) frame.fillRoundRect(x+12,y+9,10,9,4,lcd.color565(185,255,255));
    }
    // Distinct action indicators below the eyes, driven by actual voice events.
    if(state==V::Listening) {
        for(int i=0;i<5;++i) {int h=5+int((std::sin(t*5+i*.8f)+1)*7);frame.fillRoundRect(134+i*11,164-h/2,5,h,2,bright);}
    } else if(state==V::Thinking || state==V::Connecting || state==V::Boot) {
        for(int i=0;i<3;++i) {int r=3+int((std::sin(t*5-i*1.4f)+1)*2);frame.fillCircle(140+i*20,165,r,i==int(t*3)%3 ? bright : dim);}
    } else if(talking) {
        for(int i=0;i<7;++i) {float shape=1.f-std::abs(i-3)/4.f;int h=4+int(level*37*shape);frame.fillRoundRect(121+i*12,164-h/2,6,h,3,bright);}
    } else {
        frame.drawArc(160,143,25,23,35,145,dim);
    }
    frame.setTextDatum(lgfx::textdatum_t::middle_center);
    frame.setTextColor(bright,TFT_BLACK);frame.setFont(&fonts::Font2);
    frame.drawString(label(state),160,199);
    char detail[96]{};session::getStatus(detail,sizeof(detail));
    frame.setFont(&fonts::Font0);frame.setTextColor(lcd.color565(125,150,160),TFT_BLACK);
    if(state==V::Setup) {
        frame.drawString("Deskter Setup / deskter123",160,218);
        frame.drawString("Open 192.168.4.1 on your phone",160,231);
    } else if(state==V::Connecting || state==V::Error) {
        // Bounded ASCII diagnostics; credentials never enter the status string.
        detail[50]=0;frame.drawString(detail,160,222);
    } else frame.drawString("D E S K T E R",160,224);
    frame.pushSprite(0,0);
}
void fail(const char *message) {
    Serial.println(message);session::setStatus(message);session::setVisual(session::Visual::Error);
    for(;;) {if(screenReady) drawFace();delay(35);}
}
}
void appSetup() {
    Serial.begin(115200);delay(200);setCpuFrequencyMhz(settings::cpuMHz);
    if(!session::begin()) fail("Session memory init failed");
    Serial.printf("\nDESKTER animated companion / reset=%d / camera and face inference disabled\n",int(esp_reset_reason()));
    if(!psramFound()) fail("Enable OPI PSRAM");
    digitalWrite(settings::sdCs,HIGH);pinMode(settings::sdCs,OUTPUT);
    if(!lcd.init()) fail("ST7789 initialization failed");
    lcd.setColorDepth(16);lcd.setRotation(1);lcd.fillScreen(TFT_BLACK);
    frame.setColorDepth(16);frame.setPsram(true);
    if(!frame.createSprite(settings::width,settings::height)) fail("Eye framebuffer allocation failed");
    screenReady=true;session::setVisual(session::Visual::Boot);drawFace();
    if(!wakeaudio::begin()) fail("Microphone / wake model init failed");
    if(!voice::begin()) fail("Speaker / voice init failed");
    Serial.println("EYES PSRAM framebuffer, 30fps target; wake=Hey Deskter; no camera task");
}
void appLoop() {
    voice::pollSerial();
    static uint32_t nextFrame=0,lastReport=0,frames=0;
    const uint32_t now=millis();
    if(int32_t(now-nextFrame)>=0) {nextFrame=now+33;drawFace();++frames;}
    if(now-lastReport>=10000) {
        Serial.printf("EYES fps=%.1f state=%u heap=%u min_heap=%u psram=%u voice_stack=%u\n",
            frames*1000.f/(now-lastReport),unsigned(session::visual()),unsigned(ESP.getFreeHeap()),
            unsigned(ESP.getMinFreeHeap()),unsigned(ESP.getFreePsram()),voice::stackFree());
        frames=0;lastReport=now;
    }
    delay(2);
}
