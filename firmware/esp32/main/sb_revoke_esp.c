/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The secure boot digest revocation on the box (sb_revoke_esp.h).
 */
#include "sb_revoke_esp.h"

#include <string.h>

#include "esp_efuse.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_secure_boot.h"
#include "fw_update.h"
#include "sdkconfig.h"

static const char *TAG = "sb_revoke";

static uint8_t s_keys[SB_REVOKE_KEYS_MAX][32];

static size_t revoke_keys(void)
{
    int n = fw_keys_parse(CONFIG_ATALAIA_SB_REVOKE_KEYS, s_keys, SB_REVOKE_KEYS_MAX);
    if (n < 0) {
        ESP_LOGE(TAG, "CONFIG_ATALAIA_SB_REVOKE_KEYS is malformed: no revocation is accepted");
        return 0;
    }
    return (size_t)n;
}

static bool read_state(sb_state_t *s, void *ctx)
{
    (void)ctx;
    static const esp_efuse_purpose_t purposes[SB_DIGEST_SLOTS] = {
        ESP_EFUSE_KEY_PURPOSE_SECURE_BOOT_DIGEST0, ESP_EFUSE_KEY_PURPOSE_SECURE_BOOT_DIGEST1,
        ESP_EFUSE_KEY_PURPOSE_SECURE_BOOT_DIGEST2};
    memset(s, 0, sizeof(*s));
    s->secure_boot = esp_secure_boot_enabled();
    for (int i = 0; i < SB_DIGEST_SLOTS; i++) {
        esp_efuse_block_t block;
        if (esp_efuse_find_purpose(purposes[i], &block)) {
            if (esp_efuse_read_block(block, s->digest[i], 0, SB_DIGEST_LEN * 8) != ESP_OK) {
                return false;
            }
            s->present[i] = true;
        }
        s->revoked[i] = esp_efuse_get_digest_revoke((unsigned)i);
    }
    esp_image_sig_public_key_digests_t running;
    memset(&running, 0, sizeof(running));
    if (esp_secure_boot_get_signature_blocks_for_running_app(true, &running) != ESP_OK) {
        return false;
    }
    s->running_count = running.num_digests > SB_DIGEST_SLOTS ? 0 : running.num_digests;
    for (size_t i = 0; i < s->running_count; i++) {
        memcpy(s->running[i], running.key_digests[i], SB_DIGEST_LEN);
    }
    return true;
}

static bool burn_revoke(int slot, void *ctx)
{
    (void)ctx;
    ESP_LOGW(TAG, "burning SECURE_BOOT_KEY_REVOKE%d: permanent", slot);
    return esp_efuse_set_digest_revoke((unsigned)slot) == ESP_OK;
}

static const sb_revoke_ops_t OPS = {.read_state = read_state, .burn_revoke = burn_revoke};

static void hex32(const uint8_t *d, char out[65])
{
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        out[2 * i] = hex[d[i] >> 4];
        out[2 * i + 1] = hex[d[i] & 15];
    }
    out[64] = '\0';
}

void sb_revoke_esp_log_state(void)
{
    sb_state_t s;
    if (!read_state(&s, NULL)) {
        ESP_LOGW(TAG,
                 "sbdigests: the eFuses or the running image's signature blocks could not be read");
        return;
    }
    char hex[65];
    ESP_LOGI(TAG, "sbdigests: secure boot %s; %u revocation key(s)", s.secure_boot ? "on" : "OFF",
             (unsigned)revoke_keys());
    for (int i = 0; i < SB_DIGEST_SLOTS; i++) {
        if (s.present[i]) {
            hex32(s.digest[i], hex);
            ESP_LOGI(TAG, "  slot %d: %s %s", i, hex, s.revoked[i] ? "REVOKED" : "trusted");
        } else {
            ESP_LOGI(TAG, "  slot %d: empty%s", i, s.revoked[i] ? ", REVOKED" : "");
        }
    }
    for (size_t i = 0; i < s.running_count; i++) {
        hex32(s.running[i], hex);
        ESP_LOGI(TAG, "  running image signed by %s", hex);
    }
}

sb_revoke_result_t sb_revoke_esp_command(const char *text)
{
    size_t n = revoke_keys();
    int slot = -1;
    sb_revoke_result_t r = sb_revoke_run(text, (const uint8_t(*)[32])s_keys, n, &OPS, &slot);
    if (r == SB_REVOKE_DONE) {
        ESP_LOGW(TAG, "sbrevoke: secure boot digest slot %d revoked", slot);
    } else {
        ESP_LOGW(TAG, "sbrevoke refused: %s (slot %d)", sb_revoke_result_name(r), slot);
    }
    return r;
}

static void report(int index, sb_revoke_result_t r, int slot, void *ctx)
{
    (void)ctx;
    if (r == SB_REVOKE_DONE) {
        ESP_LOGW(TAG, "built-in revocation %d: secure boot digest slot %d revoked", index, slot);
    } else if (r == SB_REVOKE_ALREADY) {
        ESP_LOGI(TAG, "built-in revocation %d: slot %d revoked already", index, slot);
    } else {
        ESP_LOGE(TAG, "built-in revocation %d refused: %s (slot %d)", index,
                 sb_revoke_result_name(r), slot);
    }
}

void sb_revoke_esp_boot(void)
{
    const char *list = CONFIG_ATALAIA_SB_REVOKE_BUILTIN;
    if (list[0] == '\0') return;
    const esp_partition_t *running = esp_ota_get_running_partition();
    esp_ota_img_states_t state;
    if (running != NULL && esp_ota_get_state_partition(running, &state) == ESP_OK &&
        (state == ESP_OTA_IMG_PENDING_VERIFY || state == ESP_OTA_IMG_INVALID ||
         state == ESP_OTA_IMG_ABORTED)) {
        ESP_LOGW(TAG, "built-in revocations wait until this image is confirmed");
        return;
    }
    size_t n = revoke_keys();
    sb_revoke_run_list(list, (const uint8_t(*)[32])s_keys, n, &OPS, report, NULL);
}
