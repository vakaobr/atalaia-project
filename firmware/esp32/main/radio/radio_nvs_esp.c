/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * ESP-IDF NVS backend for the radio protocol's key and epoch storage (the per-key epoch
 * store "epochs"; the old single "epoch" is only read, for migration).
 */

#ifdef ESP_PLATFORM

#include "radio_nvs_esp.h"

#include <string.h>

#include "esp_log.h"
#include "esp_random.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

static const char *TAG = "radio_nvs";

static nvs_handle_t nvs_h;

/* ---- NVS ops -------------------------------------------------------------- */

/* The u16 "epoch" of the firmware before the per-key epoch store (read only, for migration). */
static int esp_nvs_read_legacy_epoch(void *ctx, uint16_t *epoch)
{
    (void)ctx;
    esp_err_t err = nvs_get_u16(nvs_h, "epoch", epoch);
    if (err == ESP_ERR_NVS_NOT_FOUND) return -1;
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs read epoch: %s", esp_err_to_name(err));
        return -2;
    }
    return 0;
}

/* The epoch store (radio_protocol.h): one blob, so one write replaces it whole. NVS writes the
 * new blob's entries before it erases the old ones: after a power cut it reads one or the other. */
static int esp_nvs_read_epochs(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    size_t len = cap;
    esp_err_t err = nvs_get_blob(nvs_h, "epochs", buf, &len);
    if (err == ESP_ERR_NVS_NOT_FOUND) return -1;
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs read epochs: %s", esp_err_to_name(err));
        return -2;
    }
    return (int)len;
}

static int esp_nvs_write_epochs(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    esp_err_t err = nvs_set_blob(nvs_h, "epochs", buf, len);
    if (err == ESP_OK) err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write epochs: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

/* The epoch floor (decision EP-2): the highest epoch ever used with any key, its own u16 entry
 * beside the blob, so that a loss of the blob alone does not take it. */
static int esp_nvs_read_floor(void *ctx, uint16_t *floor)
{
    (void)ctx;
    esp_err_t err = nvs_get_u16(nvs_h, "epfloor", floor);
    if (err == ESP_ERR_NVS_NOT_FOUND) return -1;
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs read epfloor: %s", esp_err_to_name(err));
        return -2;
    }
    return 0;
}

static int esp_nvs_write_floor(void *ctx, uint16_t floor)
{
    (void)ctx;
    esp_err_t err = nvs_set_u16(nvs_h, "epfloor", floor);
    if (err == ESP_OK) err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write epfloor: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

static int esp_nvs_read_key(void *ctx, uint8_t key[16])
{
    (void)ctx;
    size_t len = 16;
    esp_err_t err = nvs_get_blob(nvs_h, "game_key", key, &len);
    if (err == ESP_ERR_NVS_NOT_FOUND) return -1;
    if (err != ESP_OK || len != 16) {
        ESP_LOGE(TAG, "nvs read key: %s (len=%u)", esp_err_to_name(err), (unsigned)len);
        return -1;
    }
    return 0;
}

static int esp_nvs_write_key(void *ctx, const uint8_t key[16])
{
    (void)ctx;
    esp_err_t err = nvs_set_blob(nvs_h, "game_key", key, 16);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write key: %s", esp_err_to_name(err));
        return -1;
    }
    err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs commit key: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

static int esp_nvs_erase_key(void *ctx)
{
    (void)ctx;
    esp_err_t err = nvs_erase_key(nvs_h, "game_key");
    if (err == ESP_ERR_NVS_NOT_FOUND) return 0; /* already gone */
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs erase key: %s", esp_err_to_name(err));
        return -1;
    }
    err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs commit erase: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

/* The hardware random generator (true random with the radio on, which a running box has). */
static int esp_random_bytes(void *ctx, uint8_t *buf, size_t n)
{
    (void)ctx;
    esp_fill_random(buf, n);
    return 0;
}

static const atalaia_radio_nvs_ops_t esp_nvs_ops = {
    .read_legacy_epoch = esp_nvs_read_legacy_epoch,
    .read_epochs = esp_nvs_read_epochs,
    .write_epochs = esp_nvs_write_epochs,
    .read_key = esp_nvs_read_key,
    .write_key = esp_nvs_write_key,
    .erase_key = esp_nvs_erase_key,
    .random_bytes = esp_random_bytes,
    .read_floor = esp_nvs_read_floor,
    .write_floor = esp_nvs_write_floor,
    .ctx = NULL,
};

/* ---- Join and field join key (box_game.h) ---------------------------------- */

static int store_load_blob(const char *name, uint8_t *buf, size_t cap)
{
    size_t len = cap;
    esp_err_t err = nvs_get_blob(nvs_h, name, buf, &len);
    if (err == ESP_ERR_NVS_NOT_FOUND) return 0;
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs read %s: %s", name, esp_err_to_name(err));
        return -1;
    }
    return (int)len;
}

static int store_save_blob(const char *name, const uint8_t *buf, size_t len)
{
    esp_err_t err = nvs_set_blob(nvs_h, name, buf, len);
    if (err == ESP_OK) err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write %s: %s", name, esp_err_to_name(err));
        return -1;
    }
    return 0;
}

static int store_load_join(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    int n = store_load_blob("join", buf, cap);
    return n < 0 ? 0 : n;
}

static int store_save_join(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    return store_save_blob("join", buf, len);
}

static int store_erase_join(void *ctx)
{
    (void)ctx;
    esp_err_t err = nvs_erase_key(nvs_h, "join");
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) return -1;
    return nvs_commit(nvs_h) == ESP_OK ? 0 : -1;
}

static int store_load_join_key(void *ctx, uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return store_load_blob("join_key", key, ATALAIA_JOIN_KEY_SIZE) == ATALAIA_JOIN_KEY_SIZE ? 0
                                                                                            : -1;
}

static int store_save_join_key(void *ctx, const uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return store_save_blob("join_key", key, ATALAIA_JOIN_KEY_SIZE);
}

/* The box's device id (protocol/field-frames.md): random, made once, kept until NVS is erased. */
static int store_load_device_id(void *ctx, uint8_t id[ATALAIA_FF_DEVICE_SIZE])
{
    (void)ctx;
    return store_load_blob("device_id", id, ATALAIA_FF_DEVICE_SIZE) == ATALAIA_FF_DEVICE_SIZE ? 0
                                                                                              : -1;
}

static int store_save_device_id(void *ctx, const uint8_t id[ATALAIA_FF_DEVICE_SIZE])
{
    (void)ctx;
    return store_save_blob("device_id", id, ATALAIA_FF_DEVICE_SIZE);
}

/* The field frames' boot count (their nonces, decision RJ-15). */
static int store_load_ff_boot(void *ctx, uint32_t *boot)
{
    (void)ctx;
    esp_err_t err = nvs_get_u32(nvs_h, "ff_boot", boot);
    if (err == ESP_OK) return 0;
    if (err == ESP_ERR_NVS_NOT_FOUND) return -1; /* none stored yet */
    ESP_LOGE(TAG, "nvs read ff_boot: %s", esp_err_to_name(err));
    return -2; /* unreadable: the box sends no field frame */
}

static int store_save_ff_boot(void *ctx, uint32_t boot)
{
    (void)ctx;
    esp_err_t err = nvs_set_u32(nvs_h, "ff_boot", boot);
    if (err == ESP_OK) err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write ff_boot: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

/* Where a free box listens (RFC 0001 Amendment 19): channel and the last MOVE's revision, 8 bytes.
 */
static int store_load_field_move(void *ctx, uint32_t *channel_hz, uint32_t *rev)
{
    (void)ctx;
    uint8_t b[8];
    int n = store_load_blob("field_move", b, sizeof(b));
    if (n != (int)sizeof(b)) return -1; /* none stored yet, or unreadable: the default channel */
    *channel_hz = (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
    *rev = (uint32_t)b[4] << 24 | (uint32_t)b[5] << 16 | (uint32_t)b[6] << 8 | b[7];
    return 0;
}

static int store_save_field_move(void *ctx, uint32_t channel_hz, uint32_t rev)
{
    (void)ctx;
    uint8_t b[8] = {(uint8_t)(channel_hz >> 24), (uint8_t)(channel_hz >> 16),
                    (uint8_t)(channel_hz >> 8),  (uint8_t)channel_hz,
                    (uint8_t)(rev >> 24),        (uint8_t)(rev >> 16),
                    (uint8_t)(rev >> 8),         (uint8_t)rev};
    return store_save_blob("field_move", b, sizeof(b));
}

/* The screens' language, the last game's (join key 15; box_text.h): "" when it gave none. */
static int store_load_lang(void *ctx, char *code, size_t cap)
{
    (void)ctx;
    size_t len = cap;
    esp_err_t err = nvs_get_str(nvs_h, "lang", code, &len);
    if (err != ESP_OK) return -1; /* none stored, or unreadable: English */
    return 0;
}

static int store_save_lang(void *ctx, const char *code)
{
    (void)ctx;
    esp_err_t err = nvs_set_str(nvs_h, "lang", code);
    if (err == ESP_OK) err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write lang: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

static const box_store_ops_t esp_box_store = {
    .load_join = store_load_join,
    .save_join = store_save_join,
    .erase_join = store_erase_join,
    .load_join_key = store_load_join_key,
    .save_join_key = store_save_join_key,
    .load_device_id = store_load_device_id,
    .save_device_id = store_save_device_id,
    .load_ff_boot = store_load_ff_boot,
    .save_ff_boot = store_save_ff_boot,
    .load_field_move = store_load_field_move,
    .save_field_move = store_save_field_move,
    .load_lang = store_load_lang,
    .save_lang = store_save_lang,
    .ctx = NULL,
};

const box_store_ops_t *atalaia_box_store_esp(void)
{
    return &esp_box_store;
}

bool atalaia_nvs_encrypted(void)
{
#if CONFIG_NVS_ENCRYPTION
    return true;
#else
    return false;
#endif
}

/* ---- Public --------------------------------------------------------------- */

bool atalaia_radio_nvs_esp_wipe_epochs(bool floor_too)
{
    const char *keys[] = {"epochs", "epoch", "epfloor"};
    int n = floor_too ? 3 : 2;
    for (int i = 0; i < n; i++) {
        esp_err_t err = nvs_erase_key(nvs_h, keys[i]);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) {
            ESP_LOGE(TAG, "nvs erase %s: %s", keys[i], esp_err_to_name(err));
            return false;
        }
    }
    return nvs_commit(nvs_h) == ESP_OK;
}

const atalaia_radio_nvs_ops_t *atalaia_radio_nvs_esp_init(void)
{
    esp_err_t err = nvs_open("radio", NVS_READWRITE, &nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_open 'radio' failed: %s", esp_err_to_name(err));
        return NULL;
    }
    ESP_LOGI(TAG, "NVS namespace 'radio' opened");
    return &esp_nvs_ops;
}

#endif /* ESP_PLATFORM */
