# ESP32-C3 RDT button — TFT_eSPI / GC9A01

Updated for the supplied working GC9A01 configuration. There is no external
LED. The button connects between GPIO6 and GPIO7, so it needs no additional
connection to a GND or 3V3 header pin.

## Required button wiring change

**Disconnect the button from 5V before powering the board. Connect that lead to
GPIO7 instead. Leave its other lead on GPIO6.**

GPIO7 is configured as an output held LOW. GPIO6 uses INPUT_PULLUP, so the open
button reads HIGH and a pressed button reads LOW. Closing the button only sinks
the tiny current from the internal pull-up. GPIO7 is a reference for this button
only: never use it to supply power or ground for a display, LED, or other load.

A software setting cannot make an ESP32-C3 GPIO tolerate 5V. If 5V was previously
applied to GPIO6, damage is possible; correct wiring before testing.

The existing display power and ground remain connected. Power and ground can
also be shared by multiple components through soldered junctions, rails, or a
terminal strip if you later want a conventional GPIO6-to-GND button.

## Pin assignment

| Display / button connection | ESP32-C3 |
| --- | --- |
| TFT MOSI / DIN / SDA | GPIO4 |
| TFT SCLK / CLK / SCL | GPIO2 |
| TFT MISO | Not connected |
| TFT CS | GPIO3 |
| TFT DC | GPIO1 |
| TFT RST / RES | GPIO0 |
| Button terminal 1 | GPIO6, INPUT_PULLUP |
| Button terminal 2 | GPIO7, OUTPUT LOW |
| External LED | Removed |
| Computer USB serial | USB-C connector |

Keep the display's already-working VCC, GND, and backlight wiring. Its supply
voltage and backlight circuit depend on the module. Do not disconnect the
display's ground to make room for the button.

The design uses 7 distinct GPIOs (5 display signals plus 2 for the button).
GPIO2 is a boot-strapping pin, retained because it is in your working
configuration. Do not add circuitry that forces it LOW during reset. USB uses
the board's internal GPIO18/19 connections and needs no extra header wires.

## Arduino IDE setup

1. Select ESP32C3 Dev Module using your working esp32 board package.
2. Set Tools > USB CDC On Boot > Enabled and select the board's USB port.
3. Install TFT_eSPI by Bodmer in Library Manager. Use the same library and board
   package versions as your working example when possible.
4. If your TFT_eSPI configuration already matches the supplied settings, keep
   it. Otherwise, copy the contents of tft_setup/User_Setup.h into the installed
   TFT_eSPI library's User_Setup.h. Back up the existing file first.
5. In the library's User_Setup_Select.h, ensure its active configuration is
   #include <User_Setup.h> and no other setup-selection include is active.
   Defining pins only inside the sketch does not configure TFT_eSPI's separately
   compiled source files. The sketch checks the driver and pin assignment.
   Keep TFT_MISO set to -1 in User_Setup.h. TFT_eSPI internally remaps that
   macro to TFT_MOSI on ESP32-C3; the sketch deliberately does not compare
   TFT_MISO after including the library. This does not require a MISO wire.
6. Open arduino/HackingButton/HackingButton.ino and keep Logo.h beside it.
7. Compile and upload. If needed, hold BOOT, tap RESET, release BOOT, then upload.

The supplied User_Setup.h contains the exact requested GC9A01 driver, 240x240
dimensions, fonts, 27 MHz SPI clock and 6 MHz read clock. No Adafruit library is
required. Library updates can replace User_Setup.h; restore the working setup
after updating.

## Display and button behavior

The initialization follows your working example:
TFT_eSPI tft = TFT_eSPI(), tft.init(), tft.setRotation(0), fillScreen(),
setTextColor(), setTextDatum(MC_DATUM), and drawString().

| State | Display | USB serial |
| --- | --- | --- |
| Ready | White RDT logo, moved down 15px, READY below | None |
| Accepted press | Raw Linux-style shell begins | One ANIMATION_START line |
| Busy | Five timed phases, typed commands and scrolling output | Further presses ignored |
| Sequence ends | Logo and READY return | One ANIMATION_END line |

| Phase | Duration | Time since trigger |
| --- | --- | --- |
| ARP poisoning/spoofing | 1 second | 0-1 s |
| DNS poisoning/spoofing | 1.5 seconds | 1-2.5 s |
| Packet capture | 1 second | 2.5-3.5 s |
| Packet injection: waiting | 1 second | 3.5-4.5 s |
| Packet injection: injecting | 10 seconds | 4.5-14.5 s |

The button is locked out for the full **14.5 seconds**. Holding it never repeats
an action; release it before pressing again. Ignored presses do not restart the
timer or queue actions. A button held at startup must also be released first.

The busy screen contains only a Linux shell transcript on black: no frame,
title, simulation banner, countdown, footer, or progress bar. Normal text is
white. The root@rdt:~# prompt is cyan, successful status messages green, and the
RTP sync wait amber. The fixed-width 6x8 font, 30 columns, and 15 visible rows
fit inside the round panel. Complete commands word-wrap at spaces, retaining
every parameter, IP/MAC address, and path. Older rows scroll out of view.

Command entry is typed at 8ms per character, outputs appear at their scripted
times, and the cursor blinks. Updates run every 50ms; only changed rows and
the cursor row are repainted.

The transcript uses arpspoof, dnsspoof, tcpdump, and tcpreplay-style command
syntax with fictional hosts. It assumes its hosts file, routing configuration,
and replay capture were staged before the visible transcript. Addresses are
192.0.2.1 (gateway), 192.0.2.40 (camera), and 192.0.2.23 (intermediary); the MAC
02:7c:51:9a:10:23 and cam.example name are illustrative.

**Only strings are drawn on the TFT.** The C++ sketch has no Wi-Fi, packet
capture, ARP/DNS poisoning, or injection implementation. These commands are
never passed to a shell. The included Python callback is empty.

The ready background remains #051249. The white logo is drawn at y=15, and the
source image's stray first-row horizontal line is removed before conversion.
The original source file is retained. The existing TFT_eSPI setup is compatible.

display_preview.png shows the layout and terminal_preview.gif previews the full
14.5-second sequence. Preview fonts are illustrative; the board uses TFT_eSPI
fonts. Edit TERMINAL_SCRIPT in HackingButton.ino to customize the transcript.
Each entry has a timestamp, text, color, and typed/output flag.

## Python listener

For the RTSPoofing demo, use its existing Linux serial bridge instead of the
Python listener below (only one program should open the serial port):

    cd RTSPoofing/RTSPoofing/Trigger
    sudo ./trigger-serial.sh /dev/ttyACM0 115200

First configure `Trigger/config.ini` as described in RTSPoofing's
`Trigger/README.md`. `ANIMATION_START` starts the configured ARP spoofing and
injection; `ANIMATION_END` stops both when the full **14.5-second** animation
finishes, restoring normal camera routing. The Arduino controls the duration,
so changing `COOLDOWN_MS` needs no corresponding host timer change. Viewer
reconnection and network startup/cleanup can add latency to the visible feed.
Close Arduino Serial Monitor/Plotter before starting the bridge.

The existing listener is compatible with this firmware and is included.

From the extracted esp32_hacking_button directory:

    python -m pip install -r python/requirements.txt
    python python/serial_listener.py --list
    python python/serial_listener.py --port COM5

Replace COM5 with the actual port; on Linux this is often /dev/ttyACM0 and on
macOS /dev/cu.usbmodem.... Close Arduino Serial Monitor/Plotter first.

The function on_animation_started() deliberately contains only a comment and pass.
Put your Python action there. It is called once at the start of the animation,
not after the sequence finishes. Each accepted press sends ANIMATION_START followed
by CRLF at nominal 115200 baud. Partial reads, LF/CRLF, and boot noise are handled.

The device operates without an open serial listener. Disconnected presses are
not replayed and the one-way protocol has no acknowledgment or delivery
guarantee. Re-run the listener after a USB disconnect. The Python callback runs
synchronously and does not control the board's 14.5-second timer.

## Logo files

Logo.h already embeds the supplied RDT logo as numeric RGB565 values in flash.
The image uses 57,600 bytes of flash. No SD card or display-sized RAM buffer is
needed. Logo.bmp and logo_preview.png are included beside the sketch. The
original is assets/logo_rdt.png.

To regenerate or replace the logo:

    python -m pip install -r tools/requirements.txt
    python tools/convert_logo.py assets/logo_rdt.png --round --white --clear-top-row

The converter creates a 240x120 bitmap, preserves proportions, and composites
transparency onto #051249. --round uses the narrower RDT layout for this panel.
--white recolors its silhouette; --clear-top-row removes the original's stray line.
Without that option, artwork fits the full rectangular top half; --crop instead
scales to 120px tall and crops horizontally. Re-upload after regenerating Logo.h.
The values are compatible with TFT_eSPI pushImage() when byte swapping is enabled.

## Verification

Host-side tests cover the actual updated sketch with a mocked Arduino/TFT_eSPI
interface: pin configuration, byte-swap use for the logo, debounce, repeated and
held presses, the exact cooldown boundary, clock rollover, and disconnected
USB. Tests also check terminal typing, scrolling, all wrapped parameters being preserved,
exact phase boundaries, and one serial trigger per animation, and every text bounding box fitting within the circular
display. The Python decoder and image conversion checks also pass, including
white logo conversion, row-0 cleanup, the y=15 placement, and round-panel bounds.

The updated sketch compiles with ESP32 2.0.10, ESP32C3 Dev Module, USB CDC On
Boot enabled, and the installed TFT_eSPI configuration. Eight simulated serial
bridge checks pass, including start/end, duplicate events, EOF cleanup, failed
startup and legacy commands. No physical hardware or live camera test was run.
After upload, check READY at startup; one start event per accepted press;
terminal output for 14.5 seconds; ignored repeated/held presses; an end event
and the logo restored at expiry.

## Primary references

- TFT_eSPI: https://github.com/Bodmer/TFT_eSPI
- TFT_eSPI setup selection:
  https://github.com/Bodmer/TFT_eSPI/blob/master/User_Setup_Select.h
- Espressif GPIO voltage limits:
  https://docs.espressif.com/projects/esp-faq/en/latest/hardware-related/hardware-design.html
- Espressif USB CDC setup:
  https://docs.espressif.com/projects/arduino-esp32/en/latest/tutorials/cdc_dfu_flash.html
- pySerial: https://pyserial.readthedocs.io/en/latest/shortintro.html
- Displayed dsniff-family command syntax: https://www.kali.org/tools/dsniff/
- Displayed tcpdump command syntax:
  https://github.com/the-tcpdump-group/tcpdump-htdocs/blob/master/manpages/tcpdump.1.html
- Displayed tcpreplay command syntax:
  https://tcpreplay.appneta.com/reference/man/tcpreplay/
