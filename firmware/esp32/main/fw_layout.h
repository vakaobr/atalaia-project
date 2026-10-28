/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The flash layout this firmware expects (partitions.csv, decision PART-1), and the check a
 * box makes of the partition table it booted from. An over-the-air update cannot change the
 * partition table: a box on the old table (2 MB OTA slots, storage at 0x420000) must be
 * re-flashed over USB once. Platform-free: the ESP-IDF side (fw_update_esp.c) lists the
 * running table, the host tests list their own.
 */
#ifndef ATALAIA_FW_LAYOUT_H
#define ATALAIA_FW_LAYOUT_H

#include <stddef.h>
#include <stdint.h>

/* The table's version. 0: the tables before this one (2 MB OTA slots, no layout byte in the
 * image's descriptor); 1: 4 MB OTA slots, storage at 0x820000. Written in every image's
 * Atalaia descriptor (fw_desc_t.layout), which is how a box tells before the download that a
 * release needs a layout it is not on. */
#define FW_LAYOUT_VERSION 1

#define FW_PART_NAME_MAX 16

typedef struct {
    char name[FW_PART_NAME_MAX + 1];
    uint8_t type;    /* esp_partition_type_t: 0 app, 1 data */
    uint8_t subtype; /* esp_partition_subtype_t */
    uint32_t offset;
    uint32_t size;
} fw_part_t;

/*
 * Compares a partition table (the entries the firmware read) with the expected one: every
 * expected partition present with the same type, subtype, offset and size. Extra partitions
 * are ignored. 0 = the layout this firmware is built for; else the number of the first
 * expected partition that is missing or different, plus 1, with a short text in why
 * ("ota_0 is 0x200000 bytes, expected 0x400000").
 */
int fw_layout_check(const fw_part_t *parts, size_t count, char *why, size_t why_cap);

#endif /* ATALAIA_FW_LAYOUT_H */
