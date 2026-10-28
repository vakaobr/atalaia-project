/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The ESP32 side of the field's logo (box_logo.h): once per joined game, while the box waits for
 * the game to start, the logo is fetched on its own task over the firmware update's Wi-Fi and HTTPS
 * (fw_update_esp.h), pinned to the join's field CA.
 */
#ifndef ATALAIA_BOX_LOGO_ESP_H
#define ATALAIA_BOX_LOGO_ESP_H

#include "box_game.h"

void box_logo_esp_init(box_game_t *box);

/* On the game task, every loop: a joined game (the join names the controller, the game has not
 * started, no other fetch has the Wi-Fi) that has not asked yet starts the fetch. */
void box_logo_esp_poll(void);

#endif /* ATALAIA_BOX_LOGO_ESP_H */
