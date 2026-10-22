# Satellite

Small secondary point, beacon or "power plant": the Field Box's ESP32-S3 LoRa board (Heltec WiFi LoRa 32 V4), 2 team
buttons (a third is possible), an LED ring, the board's own small screen, one protected 18650 cell. It runs the Field
Box's firmware with fewer parts fitted, and plays the games a field controller invites it into (the `satellite` and
`master` roles of Master and Satellites, or a zone of any mode that needs only team buttons).

**To build one, follow the [build guide](BUILD.md).** The design specification's piezo buzzer is not supported by the
firmware; the guide offers the Field Box's amplifier instead (decision P5J-4).

Status: build guide written (2026-10-22); not yet built.
