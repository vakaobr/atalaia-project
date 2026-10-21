/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The ESP32 side of firmware updates (fw_update.h): the field Wi-Fi, HTTPS
 * pinned to the joined game's field CA, the esp_ota_* slot writes, the update
 * task, and the new image's confirmation after the reboot.
 */
#ifndef ATALAIA_FW_UPDATE_ESP_H
#define ATALAIA_FW_UPDATE_ESP_H

#include <stdbool.h>

#include "box_game.h"

/*
 * At boot, once the storage and the radio have come up: an image an update just
 * installed (ESP_OTA_IMG_PENDING_VERIFY) confirms itself if the radio and the
 * storage work and fw_update_self_test passes; otherwise it marks itself invalid and
 * reboots into the previous image. A crash before this point does the same through
 * the bootloader (CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE).
 */
void fw_update_esp_boot(bool radio_ok, bool storage_ok);

/* Where the update shows its progress (the shell's screen queue). */
void fw_update_esp_init(box_game_t *box, void (*screen)(const char *tmpl, const char *data_json),
                        int (*battery_pct)(void));

/*
 * An offer: CMD update's params {"id", "version"}, or "@update" on the console. Checked
 * at once (game, keys, link, version, battery: refusals are logged and shown), then run
 * on its own task; one update at a time. The box reboots into the new image when it
 * is installed.
 */
void fw_update_esp_offer(const char *params_json);

/* The field Wi-Fi a firmware update uses (stored in NVS: wifi_ssid, wifi_pass). */
bool fw_update_esp_set_wifi(const char *ssid, const char *password);

#endif /* ATALAIA_FW_UPDATE_ESP_H */
