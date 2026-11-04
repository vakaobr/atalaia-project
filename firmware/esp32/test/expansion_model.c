/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The C model of a module for the port driver's host tests (expansion_model.h). Increment 7's
 * module core replaces it.
 */
#include "expansion_model.h"

#include <string.h>

#define LEASE_LEAST 5
#define LEASE_MOST  50

void exp_model_init(exp_model_t *m, uint8_t addr, const uint8_t *ident,
                    const uint8_t *const *channels, int n)
{
    memset(m, 0, sizeof(*m));
    m->addr = addr;
    memcpy(m->ident, ident, EXP_IDENT_LEN);
    m->channels = n;
    for (int i = 0; i < n && i < EXP_CHANNELS_MAX; i++) {
        memcpy(m->channel[i], channels[i], EXP_CHANNEL_LEN);
        if (expansion_parse_channel(channels[i], EXP_CHANNEL_LEN, i, &m->ch[i]) != NULL) {
            m->ch[i].kind = 0; /* neither input nor output */
        }
    }
    exp_model_restart(m, 0);
}

void exp_model_restart(exp_model_t *m, uint32_t t)
{
    m->t = t;
    memset(m->out, 0, sizeof(m->out));
    m->lease_ms = 15 * 100;
    m->deadline_known = false;
    m->flags = EXP_ST_FRESH;
    m->armed = 0;
    m->count = 0;
    m->next_seq = 0;
    m->reg = 0xFF;
}

static bool is_output(const exp_model_t *m, int c)
{
    return c >= 0 && c < m->channels && m->ch[c].kind == EXP_KIND_OUTPUT;
}

static bool is_input(const exp_model_t *m, int c)
{
    return c >= 0 && c < m->channels && m->ch[c].kind == EXP_KIND_HIT;
}

static void out_off(exp_model_out_t *o, uint32_t t)
{
    if (o->mode != EXP_MODE_OFF) {
        o->off_known = true;
        o->last_off = t;
    }
    o->mode = EXP_MODE_OFF;
    o->on_known = false;
    o->end_known = false;
}

static bool any_on(const exp_model_t *m)
{
    for (int c = 0; c < m->channels; c++) {
        if (is_output(m, c) && m->out[c].mode != EXP_MODE_OFF) return true;
    }
    return false;
}

/* Runs the timers to t, in time order; at one moment a duration or a max on before the lease. */
static void advance(exp_model_t *m, uint32_t t)
{
    for (;;) {
        bool found = false;
        uint32_t when = 0;
        int what = 0; /* 1 end, 2 max on, 3 lease */
        int which = -1;
        for (int c = 0; c < m->channels; c++) {
            exp_model_out_t *o = &m->out[c];
            if (!is_output(m, c) || o->mode == EXP_MODE_OFF) continue;
            if (o->end_known && o->end <= t && (!found || o->end < when)) {
                found = true, when = o->end, what = 1, which = c;
            }
            uint32_t max_end = o->on_since + (uint32_t)m->ch[c].max_on_s * 1000u;
            if (o->on_known && max_end <= t && (!found || max_end < when)) {
                found = true, when = max_end, what = 2, which = c;
            }
        }
        if (m->deadline_known && any_on(m) && m->deadline <= t && (!found || m->deadline < when)) {
            found = true, when = m->deadline, what = 3;
        }
        if (!found) break;
        if (what == 3) {
            for (int c = 0; c < m->channels; c++) out_off(&m->out[c], when);
            m->flags |= EXP_ST_LEASE_EXPIRED;
            m->deadline_known = false;
        } else if (what == 2) {
            out_off(&m->out[which], when);
            m->out[which].min_off_until = when + (uint32_t)m->ch[which].min_off_s * 1000u;
        } else {
            out_off(&m->out[which], when);
        }
    }
    m->t = t;
}

static bool level(const exp_model_out_t *o, uint32_t t)
{
    if (o->mode == EXP_MODE_ON) return true;
    if (o->mode == EXP_MODE_PATTERN) {
        uint32_t period = o->on_ms + o->off_ms;
        return period > 0 && (t - o->start) % period < o->on_ms;
    }
    return false;
}

void exp_model_state(exp_model_t *m, uint32_t t, uint8_t *outputs, uint8_t *flags)
{
    advance(m, t);
    uint8_t bits = 0;
    for (int c = 0; c < m->channels; c++) {
        if (is_output(m, c) && level(&m->out[c], t)) bits |= (uint8_t)(1u << c);
    }
    if (outputs != NULL) *outputs = bits;
    if (flags != NULL) *flags = m->flags;
}

static uint16_t u16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

static const uint8_t ARG_BYTES[9] = {0, 1, 1, 8, 1, 0, 0, 1, 4};

/* NULL when taken (and applied), else the reason. */
static const char *command(exp_model_t *m, uint32_t t, const uint8_t *f, size_t len)
{
    uint8_t covered[1 + 16];
    if (len < 2 || len > 16) return len < 2 ? "crc" : "length";
    covered[0] = (uint8_t)(m->addr << 1);
    memcpy(covered + 1, f, len - 1);
    if (expansion_crc8(covered, len) != f[len - 1]) return "crc";
    size_t body = len - 1;
    if (f[0] != EXP_REG_COMMAND) return "register";
    if (body < 2) return "length";
    uint8_t op = f[1];
    if (op < EXP_OP_ACK || op > EXP_OP_CONFIG) return "op";
    const uint8_t *a = f + 2;
    if (body - 2 != ARG_BYTES[op]) return "length";
    switch (op) {
    case EXP_OP_ACK:
        if (m->count > 0 && m->q[0].seq == a[0]) {
            memmove(m->q, m->q + 1, sizeof(m->q[0]) * (size_t)(m->count - 1));
            m->count--;
        }
        m->acks++;
        return NULL;
    case EXP_OP_ARM:
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
            if ((a[0] & (1u << c)) && !is_input(m, c)) return "range";
        }
        m->armed = a[0];
        for (int i = 0; i < m->count;) {
            if (!(m->armed & (1u << m->q[i].channel))) {
                memmove(m->q + i, m->q + i + 1, sizeof(m->q[0]) * (size_t)(m->count - i - 1));
                m->count--;
            } else {
                i++;
            }
        }
        m->arms++;
        return NULL;
    case EXP_OP_OUTPUT: {
        int c = a[0];
        uint8_t mode = a[1];
        uint16_t dur = u16(a + 2), on = u16(a + 4), off = u16(a + 6);
        if (!is_output(m, c)) return "range";
        if (mode > EXP_MODE_PATTERN) return "range";
        if (mode == EXP_MODE_PATTERN) {
            uint16_t least = (m->ch[c].flags & EXP_CH_RELAY) ? 10 : 1;
            if (on < least || off < least) return "range";
        }
        exp_model_out_t *o = &m->out[c];
        if (mode == EXP_MODE_OFF) {
            out_off(o, t);
        } else {
            if (t < o->min_off_until) return "min_off";
            if ((m->ch[c].flags & EXP_CH_RELAY) && o->mode == EXP_MODE_OFF && o->off_known &&
                t - o->last_off < 100) {
                return "relay_change";
            }
            if (o->mode == EXP_MODE_OFF) {
                o->on_known = true;
                o->on_since = t;
            }
            o->mode = mode;
            o->start = t;
            o->on_ms = (uint32_t)on * 10u;
            o->off_ms = (uint32_t)off * 10u;
            o->end_known = dur != 0;
            o->end = t + (uint32_t)dur * 100u;
        }
        m->deadline_known = true;
        m->deadline = t + m->lease_ms;
        m->flags &= (uint8_t)~EXP_ST_LEASE_EXPIRED;
        m->outputs_taken++;
        return NULL;
    }
    case EXP_OP_LEASE:
        if (a[0] < LEASE_LEAST || a[0] > LEASE_MOST) return "range";
        m->lease_ms = (uint32_t)a[0] * 100u;
        m->deadline_known = true;
        m->deadline = t + m->lease_ms;
        m->flags &= (uint8_t)~EXP_ST_LEASE_EXPIRED;
        m->leases++;
        return NULL;
    case EXP_OP_ALL_OFF:
        for (int c = 0; c < m->channels; c++) out_off(&m->out[c], t);
        m->all_offs++;
        return NULL;
    case EXP_OP_CLEAR_FRESH:
        m->flags &= (uint8_t)~EXP_ST_FRESH;
        m->clear_freshes++;
        return NULL;
    case EXP_OP_LOCATE: m->locate_s = a[0]; return NULL;
    default: /* CONFIG */
        if (!is_input(m, a[0]) || a[1] < 1 || a[1] > 3) return "range";
        m->config[a[0]][a[1]] = u16(a + 2);
        return NULL;
    }
}

bool exp_model_write(exp_model_t *m, uint32_t t, const uint8_t *data, size_t len)
{
    advance(m, t);
    if (len == 1 && (data[0] == EXP_REG_IDENT || data[0] == EXP_REG_STATUS)) {
        m->reg = data[0];
        return true;
    }
    if (len == 2 && data[0] == EXP_REG_CHANNEL) {
        m->reg = data[0];
        m->index = data[1];
        return true;
    }
    m->refusal = command(m, t, data, len);
    if (m->refusal != NULL) {
        m->flags |= EXP_ST_CMD_ERROR;
        return false;
    }
    m->flags &= (uint8_t)~EXP_ST_CMD_ERROR;
    return true;
}

void exp_model_read(exp_model_t *m, uint32_t t, uint8_t *out, size_t len)
{
    uint8_t f[EXP_IDENT_LEN];
    size_t n = 0;
    memset(f, 0xFF, sizeof(f));
    advance(m, t);
    if (m->reg == EXP_REG_IDENT) {
        memcpy(f, m->ident, EXP_IDENT_LEN);
        n = EXP_IDENT_LEN;
    } else if (m->reg == EXP_REG_CHANNEL) {
        if (m->index < m->channels) {
            memcpy(f, m->channel[m->index], EXP_CHANNEL_LEN);
        } else {
            memset(f, 0, EXP_CHANNEL_LEN); /* kind 0: refused by the box */
            f[0] = m->index;
            f[7] = expansion_crc8(f, 7);
        }
        n = EXP_CHANNEL_LEN;
    } else if (m->reg == EXP_REG_STATUS) {
        uint8_t outputs, flags;
        exp_model_state(m, t, &outputs, &flags);
        bool supply = false;
        for (int c = 0; c < m->channels; c++) {
            supply = supply || (is_output(m, c) && (m->ch[c].flags & EXP_CH_SENSES));
        }
        memset(f, 0, EXP_STATUS_LEN);
        f[0] = flags & (EXP_ST_OVERFLOW | EXP_ST_LEASE_EXPIRED | EXP_ST_FRESH | EXP_ST_CMD_ERROR);
        if (supply && m->supply_ok) f[0] |= EXP_ST_SUPPLY_OK;
        if (m->count > 0) {
            const exp_model_event_t *ev = &m->q[0];
            uint32_t age = t - ev->t;
            f[0] |= EXP_ST_EVENT;
            if (m->count > 1) f[0] |= EXP_ST_MORE;
            f[1] = ev->seq;
            f[2] = (uint8_t)((ev->kind << 4) | (ev->channel & 0x07));
            f[3] = ev->value;
            if (age > 0xFFFF) age = 0xFFFF;
            f[4] = (uint8_t)(age & 0xFF);
            f[5] = (uint8_t)(age >> 8);
        }
        f[6] = outputs;
        f[7] = m->armed;
        f[8] = expansion_crc8(f, 8);
        n = EXP_STATUS_LEN;
        m->flags &= (uint8_t)~EXP_ST_OVERFLOW; /* reported */
    }
    (void)n;
    memcpy(out, f, len < sizeof(f) ? len : sizeof(f));
    if (len > sizeof(f)) memset(out + sizeof(f), 0xFF, len - sizeof(f));
}

void exp_model_hit(exp_model_t *m, uint32_t t, uint8_t channel, uint8_t kind, uint8_t value)
{
    advance(m, t);
    if (!is_input(m, channel) || !(m->armed & (1u << channel))) return;
    if (m->count == EXP_MODEL_QUEUE) {
        m->flags |= EXP_ST_OVERFLOW;
        return;
    }
    exp_model_event_t *ev = &m->q[m->count++];
    ev->seq = m->next_seq++;
    ev->channel = channel;
    ev->kind = kind;
    ev->value = value;
    ev->t = t;
}
