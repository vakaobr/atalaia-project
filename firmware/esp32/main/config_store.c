/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Config store implementation. On ESP32 this uses NVS. In stub/test
 * builds it uses a simple in-memory table.
 */
#include "config_store.h"

#include <stdio.h>
#include <string.h>

#ifdef ESP_PLATFORM

#include "nvs_flash.h"

static nvs_handle_t nvs;

int config_store_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    if (err != ESP_OK) return -1;
    return nvs_open("atalaia", NVS_READWRITE, &nvs) == ESP_OK ? 0 : -1;
}

bool config_store_is_configured(void)
{
    uint8_t val = 0;
    return nvs_get_u8(nvs, "configured", &val) == ESP_OK && val != 0;
}

void config_store_set_configured(bool configured)
{
    nvs_set_u8(nvs, "configured", configured ? 1 : 0);
    nvs_commit(nvs);
}

bool config_store_get_str(const char *key, char *out, int out_sz)
{
    size_t len = (size_t)out_sz;
    return nvs_get_str(nvs, key, out, &len) == ESP_OK;
}

void config_store_set_str(const char *key, const char *value)
{
    nvs_set_str(nvs, key, value);
    nvs_commit(nvs);
}

uint32_t config_store_get_u32(const char *key, uint32_t default_val)
{
    uint32_t val = default_val;
    nvs_get_u32(nvs, key, &val);
    return val;
}

void config_store_set_u32(const char *key, uint32_t value)
{
    nvs_set_u32(nvs, key, value);
    nvs_commit(nvs);
}

void config_store_reset(void)
{
    nvs_erase_all(nvs);
    nvs_commit(nvs);
}

#else /* In-memory store for testing. */

#define MAX_ENTRIES 32
#define KEY_MAX     32
#define VAL_MAX     128

typedef struct {
    char key[KEY_MAX];
    char val[VAL_MAX];
    uint32_t uval;
    bool is_str;
    bool used;
} config_entry_t;

static config_entry_t entries[MAX_ENTRIES];
static bool configured;

int config_store_init(void)
{
    memset(entries, 0, sizeof(entries));
    configured = false;
    return 0;
}

bool config_store_is_configured(void)
{
    return configured;
}

void config_store_set_configured(bool c)
{
    configured = c;
}

static config_entry_t *find_entry(const char *key)
{
    for (int i = 0; i < MAX_ENTRIES; i++) {
        if (entries[i].used && strcmp(entries[i].key, key) == 0) return &entries[i];
    }
    return NULL;
}

static config_entry_t *alloc_entry(const char *key)
{
    config_entry_t *e = find_entry(key);
    if (e) return e;
    for (int i = 0; i < MAX_ENTRIES; i++) {
        if (!entries[i].used) {
            entries[i].used = true;
            snprintf(entries[i].key, KEY_MAX, "%s", key);
            return &entries[i];
        }
    }
    return NULL;
}

bool config_store_get_str(const char *key, char *out, int out_sz)
{
    config_entry_t *e = find_entry(key);
    if (!e || !e->is_str) return false;
    snprintf(out, (size_t)out_sz, "%s", e->val);
    return true;
}

void config_store_set_str(const char *key, const char *value)
{
    config_entry_t *e = alloc_entry(key);
    if (!e) return;
    e->is_str = true;
    snprintf(e->val, VAL_MAX, "%s", value);
}

uint32_t config_store_get_u32(const char *key, uint32_t default_val)
{
    config_entry_t *e = find_entry(key);
    if (!e || e->is_str) return default_val;
    return e->uval;
}

void config_store_set_u32(const char *key, uint32_t value)
{
    config_entry_t *e = alloc_entry(key);
    if (!e) return;
    e->is_str = false;
    e->uval = value;
}

void config_store_reset(void)
{
    memset(entries, 0, sizeof(entries));
    configured = false;
}

#endif
