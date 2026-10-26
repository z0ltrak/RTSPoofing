#pragma once

#define USER_SETUP_INFO "ESP32-C3 Super Mini GC9A01"

#define GC9A01_DRIVER

#define TFT_WIDTH  240
#define TFT_HEIGHT 240

// ESP32-C3 Super Mini wiring
#define TFT_MOSI  4
#define TFT_SCLK  2
#define TFT_MISO -1

#define TFT_CS    3
#define TFT_DC    1
#define TFT_RST   0

// Fonts
#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8

// SPI speed
#define SPI_FREQUENCY 27000000
#define SPI_READ_FREQUENCY 6000000
