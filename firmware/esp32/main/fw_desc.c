/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Atalaia descriptor of this image (protocol/firmware-update.md): placed by
 * ESP-IDF's linker script right after esp_app_desc_t (".rodata_custom_desc", at
 * byte 288 of the image), so a box can read a downloaded image's variant and
 * board from its first bytes and refuse one built for another (decision FU3-6).
 * main/CMakeLists.txt keeps the symbol with "-u atalaia_fw_desc".
 *
 * The variant (CONFIG_ATALAIA_OTA_VARIANT): "box" for the Field Box; "box-bench" for
 * a bare board on the desk (serial keys or no setup portal: sdkconfig.bench);
 * "box-dev" for the Wokwi build (GPIO keypad, public development join key). An image
 * installs only on a box of its own variant and board.
 */
#include "fw_layout.h"
#include "fw_update.h"
#include "sdkconfig.h"

_Static_assert(sizeof(CONFIG_ATALAIA_OTA_VARIANT) <= sizeof(((fw_desc_t *)0)->variant),
               "CONFIG_ATALAIA_OTA_VARIANT: at most 11 characters");

#if CONFIG_ATALAIA_BOARD_HELTEC_V4_2
#define FW_BOARD "heltec_v4_2"
#else
#define FW_BOARD "heltec_v4_3"
#endif

const __attribute__((section(".rodata_custom_desc"))) fw_desc_t atalaia_fw_desc = {
    .magic = {'A', 'T', 'F', 'W'},
    .format = 1,
    .layout = FW_LAYOUT_VERSION,
    .reserved = {0, 0},
    .variant = CONFIG_ATALAIA_OTA_VARIANT,
    .board = FW_BOARD,
};
