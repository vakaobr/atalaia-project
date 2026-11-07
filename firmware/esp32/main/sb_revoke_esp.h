/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The ESP32-S3 side of the secure boot digest revocation (sb_revoke.h): the eFuses, the running
 * image's signature blocks and esp_efuse_set_digest_revoke. Only in a build with
 * CONFIG_ATALAIA_SB_REVOKE (the hardened release: secure boot v2 on).
 */
#ifndef ATALAIA_SB_REVOKE_ESP_H
#define ATALAIA_SB_REVOKE_ESP_H

#include "sb_revoke.h"

/* "@sbdigests": the three slots (digest, revoked or trusted), and the running image's keys. */
void sb_revoke_esp_log_state(void);

/* "@sbrevoke <digest hex> <signature base64>" (the admin PIN already checked by the caller). */
sb_revoke_result_t sb_revoke_esp_command(const char *text);

/* At boot, after fw_update_esp_boot: the instructions built into this image
 * (CONFIG_ATALAIA_SB_REVOKE_BUILTIN), once the image is confirmed (not while it is still on
 * trial after an update: a rolled-back image must not have burned anything). */
void sb_revoke_esp_boot(void);

#endif /* ATALAIA_SB_REVOKE_ESP_H */
