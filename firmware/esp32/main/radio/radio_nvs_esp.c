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
