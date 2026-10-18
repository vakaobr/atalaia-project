/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "builtin_presets.h"

#include <stdio.h>
#include <string.h>

#include "preset_store.h"

/* Parameter values are the defaults in each mode's mode.yaml (simulator/tests/test_mode_pack.py
 * checks that they agree). New entries go at the end: the picker lists presets by slot. */
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
    {"Hold-All Domination", "org.atalaia.holdall",
     "{\"capture_hold_ms\":3000,\"tick_s\":10,\"points_per_tick\":1,\"min_zones\":2}"},
    {"Last Stand", "org.atalaia.laststand",
     "{\"capture_hold_ms\":3000,\"attackers\":\"red\",\"defenders\":\"blue\",\"countdown_s\":120,"
     "\"last_zones\":1,\"min_zones\":2,\"reset\":true,\"end_game\":true}"},
    {"Codes", "org.atalaia.codes", "{\"codes\":\"\"}"},
    {"Kill Confirmed", "org.atalaia.kill_confirmed",
     "{\"confirm_points\":1,\"penalty_points\":1,\"turn_in_s\":20,\"retag_after_s\":60}"},
    {"Respawn and Lives", "org.atalaia.respawn",
     "{\"lives\":20,\"per_player\":false,\"respawn_cooldown_s\":30}"},
    {"Player Check-in", "org.atalaia.player_checkin", "{\"points\":1,\"repeat_after_s\":0}"},
};

/* preset_t holds a 16 KB source buffer, so it is not put on a task stack;
 * nor is the list of stored presets (3.7 KB). */
static preset_t scratch;
static preset_summary_t stored[PRESET_MAX_SLOTS];

static const builtin_source_t *source_of(const builtin_source_t *sources, int count,
                                         const char *mode_id)
{
    for (int j = 0; j < count; j++) {
        if (sources[j].mode_id && strcmp(sources[j].mode_id, mode_id) == 0) return &sources[j];
    }
    return NULL;
}

static bool slot_used(int count, int index)
{
    for (int i = 0; i < count; i++) {
        if (stored[i].index == index) return true;
    }
    return false;
}

int builtin_presets_seed(const builtin_source_t *sources, int source_count)
{
    int count = preset_store_list(stored, PRESET_MAX_SLOTS);
    int written = 0;
    for (size_t i = 0; i < sizeof(builtin) / sizeof(builtin[0]); i++) {
        const builtin_source_t *src = source_of(sources, source_count, builtin[i].mode_id);
        if (!src || !src->source || src->source_len >= sizeof(scratch.source)) continue;

        bool present = false;
        for (int j = 0; j < count; j++) {
            if (strcmp(stored[j].mode_id, builtin[i].mode_id) == 0) present = true;
        }
        if (present) {
            /* The firmware owns the built-in modes: an image with a newer script
             * replaces the stored one; the presets that use it stay as they are. */
            long len = preset_store_read_source(builtin[i].mode_id, scratch.source,
                                                sizeof(scratch.source));
            if (len != (long)src->source_len || memcmp(scratch.source, src->source, (size_t)len)) {
                preset_store_write_source(builtin[i].mode_id, src->source, src->source_len);
            }
            continue;
        }

        int index = 1;
        while (index <= PRESET_MAX_SLOTS && slot_used(count, index)) index++;
        if (index > PRESET_MAX_SLOTS || count >= PRESET_MAX_SLOTS) break;

        memset(&scratch, 0, sizeof(scratch));
        snprintf(scratch.mode_id, sizeof(scratch.mode_id), "%s", builtin[i].mode_id);
        snprintf(scratch.label, sizeof(scratch.label), "%s", builtin[i].label);
        snprintf(scratch.params_json, sizeof(scratch.params_json), "%s", builtin[i].params_json);
        memcpy(scratch.source, src->source, src->source_len);
        scratch.source_len = src->source_len;
        scratch.duration_s = 600;
        if (preset_store_save(index, &scratch)) {
            stored[count].index = index;
            snprintf(stored[count].mode_id, sizeof(stored[count].mode_id), "%s", scratch.mode_id);
            count++;
            written++;
        }
    }
    return written;
}
