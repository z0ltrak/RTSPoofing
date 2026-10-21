/*
 * RTSPoofing — ESP32 button trigger
 *
 * Two momentary pushbuttons, active-low with the ESP32's internal
 * pull-ups. One starts the spoofing attack on the host, the other
 * stops it. The host runs trigger-serial.sh pointing at this board's
 * USB-serial device (typically /dev/ttyACM0 on Linux).
 *
 * Wiring:
 *     GPIO 32 ──[ button ]── GND         // "spoof"
 *     GPIO 33 ──[ button ]── GND         // "normal"
 *
 * Any ESP32 dev board with USB-serial works. If your board uses a
 * CP2102 or CH340 USB bridge the port name will be /dev/ttyUSB0 —
 * pass it to trigger-serial.sh.
 *
 * Serial protocol: one lowercase word per line.
 *     "spoof"   → start the inject
 *     "normal"  → stop it
 *     "# ready" is sent on boot and ignored by the host.
 */

#define PIN_SPOOF     32
#define PIN_NORMAL    33
#define DEBOUNCE_MS   50
#define SERIAL_BAUD   9600

static int lastSpoof   = HIGH;
static int lastNormal  = HIGH;
static unsigned long lastEdgeMs = 0;

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(PIN_SPOOF,  INPUT_PULLUP);
  pinMode(PIN_NORMAL, INPUT_PULLUP);
  delay(300);                 // let USB-serial settle
  Serial.println("# ready");  // ignored by the host, visible to a human
}

void loop() {
  const unsigned long now = millis();
  const int s = digitalRead(PIN_SPOOF);
  const int n = digitalRead(PIN_NORMAL);

  if (now - lastEdgeMs > DEBOUNCE_MS) {
    // Falling edge (press) on either button.
    if (lastSpoof  == HIGH && s == LOW) {
      Serial.println("spoof");
      lastEdgeMs = now;
    } else if (lastNormal == HIGH && n == LOW) {
      Serial.println("normal");
      lastEdgeMs = now;
    }
  }
  lastSpoof  = s;
  lastNormal = n;
  delay(5);
}
