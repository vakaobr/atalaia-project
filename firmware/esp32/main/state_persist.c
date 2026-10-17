/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "state_persist.h"

#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#include "atalaia/score.h"

static char state_dir[128];
static char state_file[160];

int state_persist_init(const char *base_path)
{
    if (!base_path) return -1;
    snprintf(state_dir, sizeof(state_dir), "%s", base_path);
    snprintf(state_file, sizeof(state_file), "%s/current.bin", state_dir);
#ifndef _WIN32
    mkdir(state_dir, 0755); /* fails harmlessly when it already exists */
#endif
    return 0;
}

bool state_persist_save(const atalaia_node_t *node, const game_timer_t *timer, int preset_index,
                        uint8_t team_count)
{
    if (!node || !timer) return false;

    state_persist_data_t d;
    memset(&d, 0, sizeof(d));
    d.magic = STATE_PERSIST_MAGIC;
    d.version = STATE_PERSIST_VERSION;
    d.timer_duration_ms = timer->duration_ms;
    d.timer_elapsed_ms = timer->elapsed_ms;
    d.game_time_ms = atalaia_node_time(node);
    d.preset_index = preset_index;
    d.team_count = team_count;

    const atalaia_score_t *score = atalaia_node_score(node);
    if (score) {
        for (uint8_t t = 1; t <= team_count && t <= 8; t++) {
            d.gained[t - 1] = score->gained[t];
            d.lost[t - 1] = score->lost[t];
        }
    }

    FILE *f = fopen(state_file, "wb");
    if (!f) return false;
    size_t written = fwrite(&d, sizeof(d), 1, f);
    fclose(f);
    return written == 1;
}

bool state_persist_load(state_persist_data_t *out)
{
    if (!out) return false;

    FILE *f = fopen(state_file, "rb");
    if (!f) return false;
    size_t n = fread(out, sizeof(*out), 1, f);
    fclose(f);

    if (n != 1) return false;
    if (out->magic != STATE_PERSIST_MAGIC) return false;
    if (out->version != STATE_PERSIST_VERSION) return false;
    return true;
}

void state_persist_clear(void)
{
    remove(state_file);
}
