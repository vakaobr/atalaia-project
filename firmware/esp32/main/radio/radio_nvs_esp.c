/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * ESP-IDF NVS backend for the radio protocol's key and epoch storage.
 */

#ifdef ESP_PLATFORM

#include "radio_nvs_esp.h"

#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

static const char *TAG = "radio_nvs";

static nvs_handle_t nvs_h;

/* ---- NVS ops -------------------------------------------------------------- */

static int esp_nvs_read_epoch(void *ctx, uint16_t *epoch)
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

static int esp_nvs_write_epoch(void *ctx, uint16_t epoch)
{
    (void)ctx;
    esp_err_t err = nvs_set_u16(nvs_h, "epoch", epoch);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs write epoch: %s", esp_err_to_name(err));
        return -1;
    }
    err = nvs_commit(nvs_h);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs commit epoch: %s", esp_err_to_name(err));
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

static const atalaia_radio_nvs_ops_t esp_nvs_ops = {
    .read_epoch = esp_nvs_read_epoch,
    .write_epoch = esp_nvs_write_epoch,
    .read_key = esp_nvs_read_key,
    .write_key = esp_nvs_write_key,
    .erase_key = esp_nvs_erase_key,
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
