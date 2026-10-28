/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expected partition table (fw_layout.h). Keep it equal to partitions.csv; the host test
 * test_fw_layout.c reads that file and compares.
 */
#include "fw_layout.h"

#include <stdio.h>
#include <string.h>

/* type 0 = app, 1 = data; subtypes as ESP-IDF's esp_partition_subtype_t. */
const fw_part_t fw_layout_expected[] = {
    {"nvs", 1, 0x02, 0x9000, 0x6000},         {"otadata", 1, 0x00, 0xf000, 0x2000},
    {"phy_init", 1, 0x01, 0x11000, 0x1000},   {"nvs_keys", 1, 0x04, 0x12000, 0x1000},
    {"ota_0", 0, 0x10, 0x20000, 0x400000},    {"ota_1", 0, 0x11, 0x420000, 0x400000},
    {"storage", 1, 0x83, 0x820000, 0x400000},
};
const size_t fw_layout_expected_count = sizeof(fw_layout_expected) / sizeof(fw_layout_expected[0]);

int fw_layout_check(const fw_part_t *parts, size_t count, char *why, size_t why_cap)
{
    if (why != NULL && why_cap > 0) why[0] = '\0';
    for (size_t e = 0; e < fw_layout_expected_count; e++) {
        const fw_part_t *x = &fw_layout_expected[e];
        const fw_part_t *p = NULL;
        for (size_t i = 0; i < count; i++) {
            if (strncmp(parts[i].name, x->name, FW_PART_NAME_MAX) == 0) p = &parts[i];
        }
        if (p == NULL) {
            if (why != NULL) snprintf(why, why_cap, "%s is missing", x->name);
            return (int)e + 1;
        }
        if (p->type != x->type || p->subtype != x->subtype) {
            if (why != NULL)
                snprintf(why, why_cap, "%s is type %u/0x%02x, expected %u/0x%02x", x->name,
                         (unsigned)p->type, (unsigned)p->subtype, (unsigned)x->type,
                         (unsigned)x->subtype);
            return (int)e + 1;
        }
        if (p->offset != x->offset) {
            if (why != NULL)
                snprintf(why, why_cap, "%s is at 0x%x, expected 0x%x", x->name, (unsigned)p->offset,
                         (unsigned)x->offset);
            return (int)e + 1;
        }
        if (p->size != x->size) {
            if (why != NULL)
                snprintf(why, why_cap, "%s is 0x%x bytes, expected 0x%x", x->name,
                         (unsigned)p->size, (unsigned)x->size);
            return (int)e + 1;
        }
    }
    return 0;
}
