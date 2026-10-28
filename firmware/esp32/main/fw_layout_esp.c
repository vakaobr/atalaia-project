/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * See fw_layout_esp.h.
 */
#include "fw_layout_esp.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_partition.h"
#include "fw_layout.h"

static const char *TAG = "layout";

bool fw_layout_esp_check(char *why, unsigned why_cap)
{
    fw_part_t parts[16];
    size_t n = 0;
    esp_partition_iterator_t it =
        esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
    while (it != NULL && n < sizeof(parts) / sizeof(parts[0])) {
        const esp_partition_t *p = esp_partition_get(it);
        memset(&parts[n], 0, sizeof(parts[n]));
        strncpy(parts[n].name, p->label, FW_PART_NAME_MAX);
        parts[n].type = (uint8_t)p->type;
        parts[n].subtype = (uint8_t)p->subtype;
        parts[n].offset = p->address;
        parts[n].size = p->size;
        n++;
        it = esp_partition_next(it);
    }
    if (it != NULL) esp_partition_iterator_release(it);
    char text[96];
    if (fw_layout_check(parts, n, text, sizeof(text)) == 0) {
        ESP_LOGI(TAG, "partition table: layout %d (4 MB OTA slots), as expected",
                 FW_LAYOUT_VERSION);
        if (why != NULL && why_cap > 0) why[0] = '\0';
        return true;
    }
    ESP_LOGE(TAG,
             "WRONG PARTITION TABLE: %s. This firmware needs layout %d (4 MB OTA slots); the "
             "table is from an older one, which an over-the-air update cannot change. USB flash "
             "required once (docs/manuals/en/firmware.md).",
             text, FW_LAYOUT_VERSION);
    if (why != NULL && why_cap > 0) snprintf(why, why_cap, "%s", text);
    return false;
}
