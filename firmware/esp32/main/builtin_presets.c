/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "builtin_presets.h"

#include <stdio.h>
#include <string.h>

#include "preset_store.h"

/* Parameter values are the defaults in each mode's mode.yaml. */
static const struct {
    const char *label;
    const char *mode_id;
    const char *params_json;
} builtin[] = {
    {"Bomb", "org.atalaia.bomb",
     "{\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300,\"arm_hold_ms\":5000,"
     "\"defuse_hold_ms\":10000,\"reset_after_defuse\":false}"},
    {"Domination", "org.atalaia.domination",
     "{\"capture_hold_ms\":3000,\"tick_s\":10,\"points_per_tick\":1}"},
};

/* preset_t holds an 8 KB source buffer, so it is not put on a task stack. */
static preset_t scratch;

int builtin_presets_seed(const builtin_source_t *sources, int source_count)
{
    preset_summary_t existing[1];
    if (preset_store_list(existing, 1) > 0) return 0;

    int written = 0;
    for (size_t i = 0; i < sizeof(builtin) / sizeof(builtin[0]); i++) {
        const builtin_source_t *src = NULL;
        for (int j = 0; j < source_count; j++) {
            if (sources[j].mode_id && strcmp(sources[j].mode_id, builtin[i].mode_id) == 0) {
                src = &sources[j];
            }
        }
        if (!src || !src->source || src->source_len >= sizeof(scratch.source)) continue;

        memset(&scratch, 0, sizeof(scratch));
        snprintf(scratch.mode_id, sizeof(scratch.mode_id), "%s", builtin[i].mode_id);
        snprintf(scratch.label, sizeof(scratch.label), "%s", builtin[i].label);
        snprintf(scratch.params_json, sizeof(scratch.params_json), "%s", builtin[i].params_json);
        memcpy(scratch.source, src->source, src->source_len);
        scratch.source_len = src->source_len;
        scratch.duration_s = 600;
        if (preset_store_save(written + 1, &scratch)) written++;
    }
    return written;
}
