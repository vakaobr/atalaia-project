/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * ATALAIA_PSRAM_BSS: a big static buffer that lives in PSRAM instead of the internal RAM, when the
 * build allows it (CONFIG_SPIRAM_ALLOW_BSS_SEG_EXTERNAL_MEMORY, sdkconfig.defaults; the Wokwi,
 * modem and pod images leave it off) and plainly in .bss on the host. The internal RAM is what the
 * Wi-Fi driver, the Bluetooth controller, the display's DMA buffers and every task stack compete
 * for (firmware/esp32/README.md, "Memory budget"), and the game's data (a few KB to 17 KB each)
 * does not need it.
 *
 * Only for zero-initialised statics that tasks use: never an interrupt, never a DMA buffer and
 * never a buffer handed to a driver that needs internal RAM (SPI, I2S, RMT). ESP-IDF's flash and
 * file system code copy PSRAM buffers through internal ones, so a task may read or write those
 * to flash.
 */
#ifndef ATALAIA_PSRAM_ATTR_H
#define ATALAIA_PSRAM_ATTR_H

#ifdef ESP_PLATFORM
#include "esp_attr.h"
#define ATALAIA_PSRAM_BSS EXT_RAM_BSS_ATTR
#else
#define ATALAIA_PSRAM_BSS
#endif

#endif /* ATALAIA_PSRAM_ATTR_H */
