/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * ESP-IDF NVS implementation of atalaia_radio_nvs_ops_t.
 *
 * Stores the game key and epoch counter in an NVS namespace "radio".
 * On production boards with an eFuse HMAC key burned, NVS encryption
 * protects the game key at rest (see BRING_UP.md step 0).  On dev boards
 * without the eFuse key the key is stored in plaintext NVS with a warning.
 */
#ifndef ATALAIA_RADIO_NVS_ESP_H
#define ATALAIA_RADIO_NVS_ESP_H

#include "box_game.h"
#include "radio_protocol.h"

#ifdef ESP_PLATFORM

/*
 * Initialise the ESP NVS radio backend.  Opens the "radio" NVS namespace
 * and returns a pointer to a static atalaia_radio_nvs_ops_t that uses it.
 * Returns NULL on failure (NVS not initialised).
 */
const atalaia_radio_nvs_ops_t *atalaia_radio_nvs_esp_init(void);

/*
 * Bench only (the "@epochwipe" shell command of a bench build,
 * docs/runbooks/epoch-recovery-bench.md): removes the epoch store (the blob and the single u16 of
 * the firmware before it) so that the box, restarted, finds a stored game with no record of its key
 * and takes a lost-store epoch (RFC 0001 Amendment 23 item 5). With floor_too the epoch floor entry
 * goes as well (Amendment 25), which is the case the amendment leaves: both lost. The game key and
 * the stored game stay. True if it was done.
 */
bool atalaia_radio_nvs_esp_wipe_epochs(bool floor_too);

/*
 * The join payload ("join" blob) and the field join key ("join_key") in the
 * same namespace (box_game.h). Call after atalaia_radio_nvs_esp_init().
 */
const box_store_ops_t *atalaia_box_store_esp(void);

/* True if the NVS partition is encrypted (CONFIG_NVS_ENCRYPTION, BRING_UP.md step 0). */
bool atalaia_nvs_encrypted(void);

#endif /* ESP_PLATFORM */

#endif /* ATALAIA_RADIO_NVS_ESP_H */
