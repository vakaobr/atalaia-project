# I/O pod

ESP32-S3 LoRa board connected to an Android device over USB-OTG or BLE. Adds LoRa, big buttons, a keypad, LEDs, sound,
an NFC reader and an enclosure switch to an Android prop. It is the Field Box's hardware without its colour screen,
running the pod firmware (`python tools/docker_fw.py pod`; [firmware/esp32/README.md](../../firmware/esp32/README.md),
"The I/O pod").

**To build one, follow the [build guide](BUILD.md).**

Status: firmware written and tested on a computer (phase 3 plan phase F); build guide written (2026-10-22); not yet
built or run on a board.
