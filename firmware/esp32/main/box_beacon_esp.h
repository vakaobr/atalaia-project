/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Field Box's iBeacon on the ESP32 (decisions BBC-1 to BBC-12): NimBLE as a broadcaster
 * only (no connection, no scan, no pairing), started when the box joins a game and taken down
 * again, with its memory, when the game is over. The bytes are box_beacon.c's; this file only
 * runs the Bluetooth controller. With CONFIG_ATALAIA_BOX_BEACON off, or the Bluetooth stack not
 * in the image (the Wokwi variant), every call does nothing.
 */
#ifndef ATALAIA_BOX_BEACON_ESP_H
#define ATALAIA_BOX_BEACON_ESP_H

#include <stdbool.h>

#include "box_beacon.h"

/*
 * What the game wants: on with the box's identity (box_game_beacon), or off. Cheap and
 * non-blocking: the shell calls it every turn; the Bluetooth controller is started and stopped on
 * the beacon's own task, and only when the answer changes.
 */
void box_beacon_esp_update(bool on, const box_beacon_id_t *id);

/* True while the controller is advertising (the log and the memory monitor read it). */
bool box_beacon_esp_running(void);

#endif /* ATALAIA_BOX_BEACON_ESP_H */
