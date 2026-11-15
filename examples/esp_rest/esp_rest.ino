// Generic ESP32 text API example. Camera/microphone pins are board-specific.
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"  // Copy secrets.h.example locally. Never commit secrets.h.

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  unsigned long started=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-started<20000) delay(100);
  if(WiFi.status()!=WL_CONNECTED) {Serial.println("Wi-Fi connection failed");return;}
  configTime(0,0,"pool.ntp.org");
  time_t now=0;
  started=millis();
  while(now<1700000000 && millis()-started<15000) {time(&now);delay(100);}
  if(now<1700000000) {Serial.println("Clock unavailable; TLS requires correct time");return;}
  WiFiClientSecure client;
  client.setCACert(SERVER_ROOT_CA); // Valid current root CA for your domain.
  HTTPClient http;
  http.setTimeout(45000);
  if(!http.begin(client,String(SERVER_URL)+"/api/v1/chat")) return;
  http.addHeader("Authorization",String("Bearer ")+DEVICE_API_KEY);
  http.addHeader("Content-Type","application/json");
  JsonDocument request;
  request["text"]="তুমি কেমন আছো?";
  request["history"].to<JsonArray>();
  String body;
  serializeJson(request,body);
  int status=http.POST(body);
  if(status==200) {
    JsonDocument reply;
    if(!deserializeJson(reply,http.getStream())) {
      Serial.println(reply["text"].as<String>());
      Serial.println(reply["emotion"].as<String>());
    }
  } else Serial.printf("API failed: HTTP %d\n",status);
  http.end();
}
void loop() {delay(1000);}
