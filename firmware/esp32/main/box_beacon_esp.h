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
#include <stdint.h>

#include "box_beacon.h"

/*
 * What the game wants: on with the box's identity (box_game_beacon), or off. Cheap and
 * non-blocking: the shell calls it every turn; the Bluetooth controller is started and stopped on
 * the beacon's own task, and only when the answer changes.
 */
void box_beacon_esp_update(bool on, const box_beacon_id_t *id);

/* True while the controller is advertising (the log and the memory monitor read it). */
bool box_beacon_esp_running(void);

/*
 * Blocks (up to timeout_ms) until the Bluetooth controller is not running or starting, and returns
 * true then. The Wi-Fi driver calls it before it starts: they share the internal RAM and are never
 * up together (the shell has turned the beacon off by then, the beacon's task stops the controller
 * and gives its memory back). False after the timeout (the Wi-Fi driver tries anyway and reports
 * its own failure). Never call it from the beacon's own task or the shell loop.
 */
bool box_beacon_esp_wait_down(uint32_t timeout_ms);

#endif /* ATALAIA_BOX_BEACON_ESP_H */
