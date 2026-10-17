/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Preset storage: save, list, load and delete game presets.
 * On ESP32 this uses LittleFS; on Linux tests it uses POSIX file I/O.
 */
#ifndef ATALAIA_PRESET_STORE_H
#define ATALAIA_PRESET_STORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PRESET_MAX_SLOTS   32
#define PRESET_LABEL_MAX   48
#define PRESET_MODE_ID_MAX 64
#define PRESET_PARAMS_MAX  512
#define PRESET_SOURCE_MAX  (8 * 1024)

typedef struct {
    int index;
    char label[PRESET_LABEL_MAX];
    char mode_id[PRESET_MODE_ID_MAX];
} preset_summary_t;

typedef struct {
    char mode_id[PRESET_MODE_ID_MAX];
    char params_json[PRESET_PARAMS_MAX];
    char source[PRESET_SOURCE_MAX];
    size_t source_len;
    uint32_t duration_s; /* game duration in seconds; 0 = unlimited */
} preset_t;

/*
 * Initialise the preset store. base_path is the root directory for
 * preset files (e.g. "/littlefs" on ESP32 or a temp dir in tests).
 */
int preset_store_init(const char *base_path);

/* List all stored presets. Returns the number found (up to max_out). */
int preset_store_list(preset_summary_t *out, int max_out);

/* Load a preset by 1-based index. Returns true on success. */
bool preset_store_load(int index, preset_t *out);

/* Save a preset at the given 1-based index. Returns true on success. */
bool preset_store_save(int index, const preset_t *preset);

/* Delete a preset by 1-based index. Returns true on success. */
bool preset_store_delete(int index);

#endif /* ATALAIA_PRESET_STORE_H */
