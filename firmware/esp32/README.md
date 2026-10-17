# ESP32 firmware

ESP-IDF firmware for Field Boxes, Satellites and Android I/O pods. It embeds the shared core from `core/` and adds drivers, radio and display support.

Status: planned for phase 1.

## Device tiers

PSRAM is optional. The firmware detects it at boot and runs in the matching tier:

| Tier | Example boards | What runs |
| --- | --- | --- |
| Full | ESP32-S3 with 2–8 MB PSRAM, classic ESP32 WROVER | Node scripts, mode plus several modifiers, colour screens, cached audio |
| Reduced | ESP32 or ESP32-S3 without PSRAM (WROOM) | Node scripts as precompiled bytecode, one mode plus one modifier, audio streamed from microSD |
| Proxy | Boards that cannot run scripts | Thin node; the controller runs its logic |

## Planned components

- Drivers: buttons, keypad, WS2812 LEDs, PN532 NFC, I2S audio, fuel gauge, GPS, IMU
- Skirmesh-RF over SX1262 LoRa (RadioLib), with region limits enforced
- Screen templates rendered with LVGL
- A/B OTA updates with rollback, Ed25519-signed images
- Wi-Fi access point with a setup page for first configuration

## Radio region

The firmware refuses to transmit until a region is set (EU868 for Portugal and the rest of Europe, US915 in the Americas), and enforces that region's power and duty-cycle limits.
