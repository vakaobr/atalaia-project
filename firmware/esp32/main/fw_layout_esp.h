/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The partition table this image booted from, compared with the one it is built for
 * (fw_layout.h, partitions.csv). ESP-IDF side; every image (box, modem, pod) has it.
 */
#ifndef ATALAIA_FW_LAYOUT_ESP_H
#define ATALAIA_FW_LAYOUT_ESP_H

#include <stdbool.h>

/*
 * Reads the running partition table and compares it with the expected one. Logs the result
 * (an error naming the first difference, or the layout number on success). True if it is the
 * expected table. On false, `why` (if not NULL) holds the first difference.
 */
bool fw_layout_esp_check(char *why, unsigned why_cap);

#endif /* ATALAIA_FW_LAYOUT_ESP_H */
