/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The ESP32 side of fetching mode packages (mode_fetch.h): the mode keys built
 * into the firmware (CONFIG_ATALAIA_MODE_KEYS), the fetch on its own task over
 * the firmware update's Wi-Fi and HTTPS (fw_update_esp.h), its progress on the
 * screen, and its end handed to the game task.
 */
#ifndef ATALAIA_MODE_FETCH_ESP_H
#define ATALAIA_MODE_FETCH_ESP_H

#include <stdbool.h>
#include <stddef.h>

#include "box_game.h"

/* reduced: a Reduced box (no PSRAM); mem_limit: its Lua heap. */
void mode_fetch_esp_init(box_game_t *box, void (*screen)(const char *tmpl, const char *data_json),
                         bool reduced, size_t mem_limit);

/* box_shell_ops_t.fetch_modes: the fetch for the join starts on its own task (one at a time). */
void mode_fetch_esp_start(const atalaia_join_t *join);

/* On the game task, every loop: a fetch that is over goes to box_game_fetch_done. */
void mode_fetch_esp_poll(void);

/* How many mode keys this firmware carries (0: every package is refused, no_key). */
size_t mode_fetch_esp_key_count(void);

#endif /* ATALAIA_MODE_FETCH_ESP_H */
