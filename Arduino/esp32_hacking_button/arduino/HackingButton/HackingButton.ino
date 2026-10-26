/* ESP32-C3 Super Mini + GC9A01 240x240 + button. No external LED.
 * Install tft_setup/User_Setup.h into the TFT_eSPI library before compiling.
 * Button: GPIO6 -> button -> GPIO7. NEVER connect the button to 5V.
 * GPIO7 is driven LOW only as the button's reference, not as a power ground.
 * Board: ESP32C3 Dev Module; USB CDC On Boot: Enabled.
 */
#include <Arduino.h>
#include <TFT_eSPI.h>
#include "Logo.h"

#if !defined(CONFIG_IDF_TARGET_ESP32C3)
#error "Select ESP32C3 Dev Module in Arduino IDE."
#endif
#if !defined(ARDUINO_USB_CDC_ON_BOOT) || !ARDUINO_USB_CDC_ON_BOOT
#error "Enable Tools > USB CDC On Boot so Serial uses the USB-C port."
#endif
// Do not validate TFT_MISO here: TFT_eSPI remaps -1 to TFT_MOSI on ESP32-C3.
#if !defined(GC9A01_DRIVER) || TFT_MOSI != 4 || TFT_SCLK != 2 || TFT_CS != 3 || TFT_DC != 1 || TFT_RST != 0
#error "Install the supplied tft_setup/User_Setup.h in the TFT_eSPI library."
#endif

constexpr int BUTTON_PIN = 6;
constexpr int BUTTON_LOW_PIN = 7;
constexpr uint32_t ARP_MS = 1000;
constexpr uint32_t DNS_MS = 1500;
constexpr uint32_t CAPTURE_MS = 1000;
constexpr uint32_t INJECT_WAIT_MS = 1000;
constexpr uint32_t INJECT_MS = 10000;
constexpr uint32_t INJECT_START_MS = ARP_MS + DNS_MS + CAPTURE_MS + INJECT_WAIT_MS;
constexpr uint32_t COOLDOWN_MS = INJECT_START_MS + INJECT_MS;  // 14,500 ms.
constexpr uint32_t DEBOUNCE_MS = 30;
constexpr uint32_t FRAME_MS = 50;
constexpr int SCREEN_WIDTH = 240;
constexpr int SCREEN_HEIGHT = 240;
constexpr int CENTER_X = 120;
constexpr int LOGO_Y = 15;

constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
}
constexpr uint16_t BG = rgb565(0x05, 0x12, 0x49);
constexpr uint16_t GREEN = rgb565(0x55, 0xFF, 0xAA);
constexpr uint16_t WHITE = 0xFFFF;
constexpr uint16_t MUTED = rgb565(0x9A, 0xAF, 0xDB);

TFT_eSPI tft = TFT_eSPI();
constexpr uint16_t TERM_BG = 0x0000;
constexpr uint16_t TERM_GREEN = rgb565(0x7A, 0xFF, 0xA0);
constexpr uint16_t TERM_CYAN = rgb565(0x65, 0xE4, 0xFF);
constexpr uint16_t TERM_AMBER = rgb565(0xFF, 0xCE, 0x70);
constexpr int TERM_X = 30;
constexpr int TERM_Y = 46;
constexpr int TERM_COLS = 30;
constexpr int TERM_ROWS = 15;
constexpr int TERM_CELL_W = 6;
constexpr int TERM_LINE_H = 10;
constexpr uint32_t TYPE_CHAR_MS = 8;

// Display-only fiction: no Wi-Fi, RTSP client, packet capture, or injection code.
struct TerminalLine {
  uint32_t atMs;
  const char *text;
  uint16_t color;
  bool typed;
};
const TerminalLine TERMINAL_SCRIPT[] = {
  {    0, "root@rdt:~# arpspoof -i wlan0 -t 192.0.2.40 -r 192.0.2.1 &", WHITE, true},
  {  650, "192.0.2.1 is-at 02:7c:51:9a:10:23", WHITE, false},
  {  850, "ARP cache updated", TERM_GREEN, false},
  { 1000, "root@rdt:~# dnsspoof -i wlan0 -f /tmp/dns.hosts &", WHITE, true},
  { 1550, "dnsspoof: listening on wlan0", WHITE, false},
  { 1900, "A cam.example -> 192.0.2.23", WHITE, false},
  { 2300, "DNS reply accepted", TERM_GREEN, false},
  { 2500, "root@rdt:~# tcpdump -ni wlan0 -c 32 -w /tmp/rtp.pcap 'udp port 5004'", WHITE, true},
  { 3200, "tcpdump: listening on wlan0", WHITE, false},
  { 3350, "IP 192.0.2.40.5004 > 192.0.2.23.5004: UDP, length 1200", WHITE, false},
  { 3450, "32 packets captured", WHITE, false},
  { 3500, "root@rdt:~# tcpreplay -i wlan0 -p 1200 -l 0 --duration=10 --stats=1 /tmp/video.pcap", WHITE, true},
  { 4350, "Waiting for RTP sync...", TERM_AMBER, false},
  { 4500, "tcpreplay: sending packets", TERM_GREEN, false},
  { 5500, "Actual: 1200 packets / 1.00 seconds", WHITE, false},
  { 5650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  { 6500, "Actual: 2400 packets / 2.00 seconds", WHITE, false},
  { 6650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  { 7500, "Actual: 3600 packets / 3.00 seconds", WHITE, false},
  { 7650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  { 8500, "Actual: 4800 packets / 4.00 seconds", WHITE, false},
  { 8650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  { 9500, "Actual: 6000 packets / 5.00 seconds", WHITE, false},
  { 9650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  {10500, "Actual: 7200 packets / 6.00 seconds", WHITE, false},
  {10650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  {11500, "Actual: 8400 packets / 7.00 seconds", WHITE, false},
  {11650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  {12500, "Actual: 9600 packets / 8.00 seconds", WHITE, false},
  {12650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  {13500, "Actual: 10800 packets / 9.00 seconds", WHITE, false},
  {13650, "Rated: 11.52 Mbps, 1200 pps", WHITE, false},
  {14000, "Successful packets: 11400", WHITE, false},
  {14200, "Failed packets: 0", WHITE, false},
};
constexpr int TERMINAL_LINE_COUNT = sizeof(TERMINAL_SCRIPT) / sizeof(TERMINAL_SCRIPT[0]);
char terminalCache[TERM_ROWS][TERM_COLS + 1] = {};
uint16_t terminalColorCache[TERM_ROWS] = {};
struct TerminalRow {
  char text[TERM_COLS + 1];
  uint16_t color;
  int sourceLine;
};
TerminalRow terminalBuffer[TERM_ROWS];
bool busy = false;
bool rawButton = HIGH;
bool stableButton = HIGH;
bool buttonArmed = false;
bool rawPressEligible = false;
uint32_t rawChangedAt = 0;
uint32_t busySince = 0;
uint32_t lastFrameAt = 0;

void centeredText(const char *text, int16_t y, uint8_t font, uint16_t color) {
  tft.setTextSize(1);
  tft.setTextColor(color, BG);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(text, CENTER_X, y, font);
}

void drawReady() {
  tft.fillScreen(BG);
  if (LOGO_AVAILABLE) {
    // Normal RGB565 values in flash; TFT_eSPI needs byte swapping for pushImage.
    tft.setSwapBytes(true);
    tft.pushImage((SCREEN_WIDTH - LOGO_WIDTH) / 2, LOGO_Y,
                  LOGO_WIDTH, LOGO_HEIGHT, LOGO_RGB565);
    tft.setSwapBytes(false);
  } else {
    centeredText("YOUR LOGO", 87, 4, WHITE);
  }
  tft.drawFastHLine(48, 142, 144, MUTED);
  centeredText("READY", 166, 4, GREEN);
  centeredText("PRESS BUTTON", 194, 2, WHITE);
}

void drawTerminalShell() {
  tft.fillScreen(TERM_BG);
  tft.setTextSize(1);
  tft.setTextWrap(false, false);
  tft.setTextDatum(TL_DATUM);
  memset(terminalCache, 0, sizeof(terminalCache));
  memset(terminalColorCache, 0, sizeof(terminalColorCache));
}

void appendTerminalRow(const char *text, size_t length, uint16_t color,
                       int sourceLine, int &totalRows) {
  TerminalRow &row = terminalBuffer[totalRows % TERM_ROWS];
  memcpy(row.text, text, length);
  row.text[length] = '\0';
  row.color = color;
  row.sourceLine = sourceLine;
  ++totalRows;
}

int buildTerminalRows(uint32_t elapsed) {
  int totalRows = 0;
  for (int i = 0; i < TERMINAL_LINE_COUNT; ++i) {
    const TerminalLine &line = TERMINAL_SCRIPT[i];
    if (elapsed < line.atMs) break;
    size_t count = strlen(line.text);
    if (line.typed) {
      const uint32_t typed = (elapsed - line.atMs) / TYPE_CHAR_MS;
      if (typed < count) count = typed;
    }
    // Word-wrap complete command parameters instead of cutting them off.
    // A ring buffer retains the most recent 15 physical terminal rows.
    size_t start = 0;
    do {
      const size_t remaining = count - start;
      size_t take = remaining < TERM_COLS ? remaining : TERM_COLS;
      if (remaining > TERM_COLS) {
        size_t space = take;
        while (space > 0 && line.text[start + space] != ' ') --space;
        if (space > 0) take = space;
      }
      appendTerminalRow(line.text + start, take, line.color, i, totalRows);
      start += take;
      while (start < count && line.text[start] == ' ') ++start;
    } while (start < count);
  }
  return totalRows;
}

void drawBusyFrame(uint32_t now) {
  const uint32_t elapsed = static_cast<uint32_t>(now - busySince);
  const int totalRows = buildTerminalRows(elapsed);
  const int first = totalRows > TERM_ROWS ? totalRows - TERM_ROWS : 0;
  const int visibleRows = totalRows - first;
  const int activeRow = visibleRows - 1;

  tft.setTextSize(1);
  tft.setTextDatum(TL_DATUM);
  for (int row = 0; row < TERM_ROWS; ++row) {
    const TerminalRow *content = row < visibleRows
        ? &terminalBuffer[(first + row) % TERM_ROWS] : nullptr;
    const char *text = content ? content->text : "";
    const uint16_t color = content ? content->color : WHITE;
    if (strcmp(terminalCache[row], text) != 0 ||
        terminalColorCache[row] != color || row == activeRow) {
      const int y = TERM_Y + row * TERM_LINE_H;
      tft.fillRect(TERM_X, y, TERM_COLS * TERM_CELL_W, TERM_LINE_H, TERM_BG);
      tft.setTextColor(color, TERM_BG);
      tft.drawString(text, TERM_X, y, 1);

      // Color only the Linux prompt; commands and normal output stay white.
      if (strncmp(text, "root@rdt:~#", 11) == 0) {
        tft.setTextColor(TERM_CYAN, TERM_BG);
        tft.drawString("root@rdt:~#", TERM_X, y, 1);
      }
      strcpy(terminalCache[row], text);
      terminalColorCache[row] = color;
      const int cursorCol = strlen(text);
      if (row == activeRow && cursorCol < TERM_COLS && (elapsed / 300) % 2 == 0)
        tft.fillRect(TERM_X + cursorCol * TERM_CELL_W, y + 1, 4, 7, WHITE);
    }
  }
}

void startCooldown(uint32_t now) {
  busy = true;
  busySince = now;
  if (Serial) Serial.println("ANIMATION_START");
  drawTerminalShell();
  lastFrameAt = now;
  drawBusyFrame(now);
}

void updateButton(uint32_t now) {
  const bool reading = digitalRead(BUTTON_PIN);
  if (reading != rawButton) {
    rawButton = reading;
    rawChangedAt = now;
    if (reading == LOW) rawPressEligible = !busy;
  }
  if (rawButton == stableButton ||
      static_cast<uint32_t>(now - rawChangedAt) < DEBOUNCE_MS) return;

  stableButton = rawButton;
  if (stableButton == HIGH) {
    buttonArmed = true;
  } else {
    if (buttonArmed && rawPressEligible && !busy) startCooldown(now);
    buttonArmed = false;  // Held and cooldown presses never repeat or queue.
  }
}

void setup() {
  // GPIO7 only sinks the tiny current from GPIO6's internal pull-up.
  // Never use GPIO7 to power a display, LED, or other load.
  pinMode(BUTTON_LOW_PIN, OUTPUT);
  digitalWrite(BUTTON_LOW_PIN, LOW);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  rawButton = stableButton = digitalRead(BUTTON_PIN);
  buttonArmed = (stableButton == HIGH);
  rawChangedAt = millis();

  Serial.begin(115200);
  // TFT_eSPI owns SPI setup and display initialization, matching the example.
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(BG);
  tft.setTextColor(TFT_WHITE, BG);
  tft.setTextDatum(MC_DATUM);
  drawReady();
}

void loop() {
  const uint32_t now = millis();
  if (busy && static_cast<uint32_t>(now - busySince) >= COOLDOWN_MS) {
    busy = false;
    if (Serial) Serial.println("ANIMATION_END");
    drawReady();
  }
  updateButton(now);
  if (busy && static_cast<uint32_t>(now - lastFrameAt) >= FRAME_MS) {
    lastFrameAt = now;
    drawBusyFrame(now);
  }
  delay(1);  // Sample the button frequently; terminal updates every 50ms.
}
