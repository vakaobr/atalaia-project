/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A simulated module on the real module core (module_sim.h).
 */
#include "module_sim.h"

#include <string.h>

static void sim_set_output(void *ctx, uint8_t channel, bool on)
{
    module_sim_t *m = (module_sim_t *)ctx;
    if (channel >= MC_MAX_CHANNELS) return;
    if (on) {
        m->outputs = (uint8_t)(m->outputs | (1u << channel));
    } else {
        m->outputs = (uint8_t)(m->outputs & ~(1u << channel));
    }
}

static void make_frames(module_sim_t *m)
{
    mc_ident_encode(&m->cfg, m->ident);
    memset(m->channel, 0xFF, sizeof(m->channel));
    for (uint8_t i = 0; i < m->cfg.channel_count && i < MC_MAX_CHANNELS; i++) {
        mc_channel_encode(&m->cfg, i, m->channel[i]);
    }
}

static bool start(module_sim_t *m, uint32_t now_ms)
{
    mc_ops_t ops = {.ctx = m, .set_output = sim_set_output, .supply_ok = NULL};
    m->outputs = 0;
    m->pointer = 0xFF;
    m->pointer_index = 0;
    m->ok = mc_init(&m->core, &m->cfg, &ops, now_ms);
    return m->ok;
}

bool module_sim_init(module_sim_t *m, const mc_config_t *cfg, uint32_t now_ms)
{
    memset(m, 0, sizeof(*m));
    m->cfg = *cfg;
    make_frames(m);
    return start(m, now_ms);
}

bool module_sim_from_frames(module_sim_t *m, uint8_t addr, const uint8_t *ident,
                            const uint8_t *const *channels, int n)
{
    mc_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.address = addr;
    cfg.model = (uint16_t)(ident[5] | (ident[6] << 8));
    cfg.hw_rev = ident[7];
    memcpy(cfg.fw, &ident[8], 3);
    memcpy(cfg.uid, &ident[11], 4);
    cfg.channel_count = (uint8_t)(n < 0 ? 0 : n > (int)MC_MAX_CHANNELS ? (int)MC_MAX_CHANNELS : n);
    for (uint8_t i = 0; i < cfg.channel_count; i++) {
        const uint8_t *c = channels[i];
        mc_channel_t *ch = &cfg.channels[i];
        ch->kind = c[1];
        ch->flags = c[2];
        ch->hint = c[3];
        ch->max_on_s = c[4];
        ch->min_off_s = c[5];
        if (ch->kind == MC_KIND_HIT) {
            ch->threshold = 200;
            ch->holdoff_ms = 50;
        }
    }
    bool ok = module_sim_init(m, &cfg, 0);
    /* What the box reads is the reference module's own bytes. */
    memcpy(m->ident, ident, MC_IDENT_LEN);
    for (int i = 0; i < n && i < (int)MC_MAX_CHANNELS; i++) {
        memcpy(m->channel[i], channels[i], MC_CHANNEL_LEN);
    }
    return ok;
}

bool module_sim_named(module_sim_t *m, const char *name, uint8_t addr, uint32_t now_ms)
{
    mc_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.fw[0] = 1;
    if (strcmp(name, "target") == 0) {
        cfg.address = addr ? addr : 0x58;
        cfg.model = 0x0001;
        cfg.hw_rev = 1;
        cfg.uid[0] = 0xE6;
        cfg.uid[1] = 0x61;
        cfg.uid[2] = 0x41;
        cfg.uid[3] = cfg.address;
        cfg.channel_count = 1;
        cfg.channels[0] = (mc_channel_t){.kind = MC_KIND_HIT, .threshold = 200, .holdoff_ms = 50};
    } else if (strcmp(name, "out4") == 0) {
        static const uint8_t hints[4] = {1, 2, 3, 0};
        static const uint8_t max_on[4] = {60, 120, 30, 255};
        static const uint8_t min_off[4] = {0, 0, 30, 0};
        cfg.address = addr ? addr : 0x5C;
        cfg.model = 0x0002;
        cfg.hw_rev = 2;
        cfg.uid[0] = 0xA1;
        cfg.uid[1] = 0xB2;
        cfg.uid[2] = 0xC3;
        cfg.uid[3] = cfg.address;
        cfg.channel_count = 4;
        for (int i = 0; i < 4; i++) {
            cfg.channels[i] = (mc_channel_t){.kind = MC_KIND_OUTPUT,
                                             .flags = MC_CH_RELAY,
                                             .hint = hints[i],
                                             .max_on_s = max_on[i],
                                             .min_off_s = min_off[i]};
        }
    } else {
        return false;
    }
    if (cfg.address < MC_FIRST_ADDRESS || cfg.address > MC_LAST_ADDRESS) return false;
    return module_sim_init(m, &cfg, now_ms);
}

void module_sim_restart(module_sim_t *m, uint32_t now_ms)
{
    start(m, now_ms);
}

static void count_taken(module_sim_t *m, uint8_t op)
{
    switch (op) {
    case MC_OP_ACK: m->acks++; break;
    case MC_OP_ARM: m->arms++; break;
    case MC_OP_OUTPUT: m->outputs_taken++; break;
    case MC_OP_LEASE: m->leases++; break;
    case MC_OP_ALL_OFF: m->all_offs++; break;
    case MC_OP_CLEAR_FRESH: m->clear_freshes++; break;
    case MC_OP_LOCATE: m->locates++; break;
    case MC_OP_CONFIG: m->configs++; break;
    default: break;
    }
}

bool module_sim_write(module_sim_t *m, uint32_t now_ms, const uint8_t *data, size_t len)
{
    if (!m->ok) return false;
    bool pointer = (len == 1 && (data[0] == MC_REG_IDENT || data[0] == MC_REG_STATUS)) ||
                   (len == 2 && data[0] == MC_REG_CHANNEL);
    mc_result_t r = mc_write(&m->core, data, len, now_ms);
    if (pointer) {
        m->pointer = data[0];
        m->pointer_index = len == 2 ? data[1] : 0;
        return true;
    }
    if (len == 0) return true;
    m->refusal = r == MC_OK ? NULL : mc_result_name(r);
    if (r == MC_OK && len > 1) count_taken(m, data[1]);
    return r == MC_OK;
}

void module_sim_read(module_sim_t *m, uint32_t now_ms, uint8_t *out, size_t len)
{
    if (!m->ok) {
        memset(out, 0xFF, len);
        return;
    }
    if (m->pointer == MC_REG_IDENT || m->pointer == MC_REG_CHANNEL) {
        /* The frames kept here (a test may have spoilt them); the core still sees the read. */
        uint8_t ignored[MC_MAX_READ_LEN];
        mc_read(&m->core, ignored, len < sizeof(ignored) ? len : sizeof(ignored), now_ms);
        const uint8_t *src = NULL;
        size_t have = 0;
        if (m->pointer == MC_REG_IDENT) {
            src = m->ident;
            have = MC_IDENT_LEN;
        } else if (m->pointer_index < m->cfg.channel_count) {
            src = m->channel[m->pointer_index];
            have = MC_CHANNEL_LEN;
        }
        for (size_t i = 0; i < len; i++) out[i] = i < have ? src[i] : 0xFF;
        return;
    }
    mc_read(&m->core, out, len, now_ms);
}

bool module_sim_hit(module_sim_t *m, uint32_t now_ms, uint8_t channel, uint8_t kind, uint8_t value)
{
    if (!m->ok) return false;
    mc_tick(&m->core, now_ms);
    return mc_event(&m->core, channel, kind, value, now_ms);
}

void module_sim_state(module_sim_t *m, uint32_t now_ms, uint8_t *outputs, uint8_t *flags)
{
    if (m->ok) mc_tick(&m->core, now_ms);
    if (outputs != NULL) *outputs = m->ok ? mc_outputs(&m->core) : 0;
    if (flags != NULL) *flags = m->ok ? mc_status_flags(&m->core) : 0;
}

uint8_t module_sim_armed(const module_sim_t *m)
{
    return m->ok ? mc_armed(&m->core) : 0;
}

int module_sim_queued(const module_sim_t *m)
{
    return m->ok ? m->core.count : 0;
}
