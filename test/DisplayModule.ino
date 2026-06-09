#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

const int SCREEN_WIDTH = 128;
const int SCREEN_HEIGHT = 64;
const int OLED_RESET = -1;

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

String lastTx = "";
String lastRx = "";

bool initDisplay() {
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    return false;
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("LoRa Chat Init...");
  display.display();

  return true;
}

void showLoRaFailure() {
  display.println("LoRa FAIL!");
  display.display();
}

void showReady() {
  display.clearDisplay();
  display.setCursor(0, 0);
  display.println("Team 02 Ready!");
  display.display();
}

void refreshDisplay() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.print("TX: ");
  display.println(lastTx.length() > 18 ? lastTx.substring(0, 18) : lastTx);

  display.drawLine(0, 12, 127, 12, SSD1306_WHITE);

  display.setCursor(0, 16);
  display.print("RX: ");
  display.println(lastRx.length() > 18 ? lastRx.substring(0, 18) : lastRx);

  display.display();
}

void setDisplayTx(const String& message) {
  lastTx = message;
  refreshDisplay();
}

void setDisplayRx(const String& message) {
  lastRx = message;
  refreshDisplay();
}
