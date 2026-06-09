#include <SPI.h>
#include <LoRa.h>

bool initDisplay();
void showLoRaFailure();
void showReady();
void setDisplayTx(const String& message);
void setDisplayRx(const String& message);

String inputLine = "";

void setup() {
  Serial.begin(115200);
  while (!Serial);

  if (!initDisplay()) {
    Serial.println("[ERROR] OLED 초기화 실패");
    while (true);
  }

  LoRa.setPins(18, 14, 26);       

  if (!LoRa.begin(915E6)) {       
    Serial.println("[ERROR] LoRa 초기화 실패. 하드웨어 확인!");
    showLoRaFailure();
    while (true);
  }

  LoRa.setSpreadingFactor(9);      
  LoRa.setSignalBandwidth(125E3); 
  LoRa.setCodingRate4(8);        
  LoRa.setTxPower(20);         
  LoRa.setSyncWord(0x55);        
  LoRa.enableCrc();            

  Serial.println("============================");
  Serial.println("  LoRa Chat Ready (Team 02) ");
  Serial.println("  메시지 입력 후 Enter       ");
  Serial.println("============================");

  showReady();
}

void loop() {
  handleSerialInput();
  handleLoRaReceive();
}

void handleSerialInput() {
  while (Serial.available()) {
    char c = (char)Serial.read();

    if (c == '\n' || c == '\r') {
      inputLine.trim();
      if (inputLine.length() > 0) {
        LoRa.beginPacket();
        LoRa.print(inputLine);
        LoRa.endPacket();

        Serial.print("[TX] ");
        Serial.println(inputLine);

        setDisplayTx(inputLine);
        inputLine = "";
      }
    } else {
      inputLine += c;
    }
  }
}

void handleLoRaReceive() {
  int packetSize = LoRa.parsePacket();
  if (packetSize) {
    String received = "";
    while (LoRa.available()) {
      received += (char)LoRa.read();
    }
    int rssi = LoRa.packetRssi();
    float snr  = LoRa.packetSnr();

    Serial.print("[RX] ");
    Serial.print(received);
    Serial.print("  RSSI: ");
    Serial.print(rssi);
    Serial.print(" dBm  SNR: ");
    Serial.print(snr);
    Serial.println(" dB");

    setDisplayRx(received);
  }
}
