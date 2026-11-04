/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target module's portable part (target.h).
 */
#include "target.h"

#include <string.h>

bool target_config(mc_config_t *cfg, uint8_t jumpers, uint8_t channels, const uint8_t uid[4],
                   uint16_t threshold, uint16_t holdoff_ms)
{
    if (jumpers > 3u || channels < 1u || channels > 2u) return false;
    memset(cfg, 0, sizeof(*cfg));
    cfg->address = (uint8_t)(TARGET_ADDRESS + jumpers);
    cfg->model = TARGET_MODEL;
    cfg->hw_rev = TARGET_HW_REV;
    cfg->fw[0] = TARGET_FW_MAJOR;
    cfg->fw[1] = TARGET_FW_MINOR;
    cfg->fw[2] = TARGET_FW_PATCH;
    memcpy(cfg->uid, uid, 4);
    cfg->channel_count = channels;
    for (uint8_t c = 0; c < channels; c++) {
        cfg->channels[c].kind = MC_KIND_HIT;
        cfg->channels[c].threshold = threshold;
        cfg->channels[c].holdoff_ms = holdoff_ms;
    }
    return true;
}

void target_i2c_init(target_i2c_t *t, mc_module_t *core)
{
    t->core = core;
    t->state = 0;
}

uint8_t target_i2c_event(target_i2c_t *t, target_i2c_event_t ev, uint8_t in, uint32_t now_ms)
{
    switch (ev) {
    case TARGET_I2C_RECEIVE:
        if (t->state != 1u) {
            if (t->state == 2u) mc_i2c_stop(t->core, now_ms);
            mc_i2c_start(t->core, false, now_ms);
            t->state = 1u;
        }
        mc_i2c_receive(t->core, in);
        return 0;
    case TARGET_I2C_REQUEST:
        if (t->state != 2u) {
            /* A start (or a repeated start after the pointer write): the write is taken now. */
            mc_i2c_start(t->core, true, now_ms);
            t->state = 2u;
        }
        return mc_i2c_request(t->core);
    case TARGET_I2C_FINISH:
        if (t->state != 0u) mc_i2c_stop(t->core, now_ms);
        t->state = 0u;
        return 0;
    }
    return 0;
}

bool target_led(mc_module_t *core, uint32_t now_ms)
{
    if (!mc_locating(core, now_ms)) return false;
    return (now_ms / TARGET_LOCATE_MS) % 2u == 0u;
}
