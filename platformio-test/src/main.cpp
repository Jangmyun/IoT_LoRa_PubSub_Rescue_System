#include <Arduino.h>

void setup() {
  Serial.begin(115200);
  Serial.println("PlatformIO + TTGO LoRa32 OK");
}

void loop() {
  Serial.println("tick");
  delay(1000);
}