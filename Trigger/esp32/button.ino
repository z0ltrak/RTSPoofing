/*
 * RTSPoofing — ESP32 command trigger
 *
 * A small panel of momentary pushbuttons. Each button is bound to one
 * command *word*; pressing it prints that word (one lowercase token per
 * line) over USB-serial. The host runs trigger-serial.sh, which reads
 * those words and dispatches the matching `rtspoof-ctl` subcommand.
 *
 * To add, remove, or re-label a button, edit the BUTTONS table below —
 * nothing else in the sketch needs to change. The words here must match
 * the ones trigger-serial.sh knows about (see CMD_MAP in that script);
 * the two tables are the contract between the board and the host.
 *
 * Buttons are active-low using the ESP32's internal pull-ups, so each
 * one is just:
 *
 *     GPIO <pin> ──[ button ]── GND
 *
 * Any ESP32 dev board with USB-serial works. A CP2102/CH340 bridge
 * shows up as /dev/ttyUSB0 rather than /dev/ttyACM0 — pass the right
 * path to trigger-serial.sh.
 *
 * Serial protocol: one lowercase word per line at 9600 bps.
 *     attack   → full MITM   (rtspoof-ctl: arpspoof on + spoof)
 *     reset    → all off      (rtspoof-ctl: panic)
 *     spoof    → inject proxy (rtspoof-ctl: spoof)
 *     normal   → proxy off    (rtspoof-ctl: normal)
 *     arpspoof → ARP poison   (rtspoof-ctl: arpspoof on)
 *     status   → report state (rtspoof-ctl: status)
 * Lines beginning with '#' are diagnostics for a human and are ignored
 * by the host ("# ready" on boot, "# <pin>:<word>" in the banner).
 */

#define DEBOUNCE_MS   50
#define SERIAL_BAUD   9600

struct Button {
  uint8_t      pin;    // GPIO wired to the button (other leg to GND)
  const char  *word;   // command word printed on press
  int          last;   // previous reading (runtime state)
  unsigned long edge;  // millis() of the last accepted edge (debounce)
};

// ---- the panel -----------------------------------------------------------
// Wire one button per row. Avoid strapping/input-only pins if you extend
// this: GPIO 34–39 are input-only (no pull-ups), and 0/2/15 affect boot.
// The defaults below (32/33/25/26/27/14) are all safe, pull-up-capable.
static Button BUTTONS[] = {
  { 32, "attack",   HIGH, 0 },   // one press: arpspoof + inject
  { 33, "reset",    HIGH, 0 },   // one press: stop everything, restore host
  { 25, "spoof",    HIGH, 0 },   // inject proxy only
  { 26, "normal",   HIGH, 0 },   // stop the proxy only
  { 27, "arpspoof", HIGH, 0 },   // ARP poison only (no inject)
  { 14, "status",   HIGH, 0 },   // ask the host to report state
};
static const size_t N_BUTTONS = sizeof(BUTTONS) / sizeof(BUTTONS[0]);

void setup() {
  Serial.begin(SERIAL_BAUD);
  for (size_t i = 0; i < N_BUTTONS; i++) {
    pinMode(BUTTONS[i].pin, INPUT_PULLUP);
    BUTTONS[i].last = HIGH;
    BUTTONS[i].edge = 0;
  }
  delay(300);                 // let USB-serial settle

  // Banner: a human (or `cat /dev/ttyACM0`) can see the wiring map.
  // All '#' lines are ignored by the host dispatcher.
  Serial.println("# ready");
  for (size_t i = 0; i < N_BUTTONS; i++) {
    Serial.print("# GPIO ");
    Serial.print(BUTTONS[i].pin);
    Serial.print(" -> ");
    Serial.println(BUTTONS[i].word);
  }
}

void loop() {
  const unsigned long now = millis();
  for (size_t i = 0; i < N_BUTTONS; i++) {
    const int reading = digitalRead(BUTTONS[i].pin);
    // Falling edge (press), debounced per-button so two buttons can be
    // pressed in quick succession without one swallowing the other.
    if (BUTTONS[i].last == HIGH && reading == LOW &&
        now - BUTTONS[i].edge > DEBOUNCE_MS) {
      Serial.println(BUTTONS[i].word);
      BUTTONS[i].edge = now;
    }
    BUTTONS[i].last = reading;
  }
  delay(5);
}
