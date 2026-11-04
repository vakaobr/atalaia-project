/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The module core (module_core.h; draft RFC "The expansion port", increment 7). The outputs follow
 * protocol/expansion-port.md section 4 as the Python reference model does
 * (simulator/atalaia_sim/expansion.py, ModuleModel), and the vectors' timelines check both.
 */
#include "module_core.h"

#include <string.h>

/* Each op's argument bytes (after the register and the op). */
static const uint8_t op_args[9] = {0, 1, 1, 8, 1, 0, 0, 1, 4};

/* a is at or after b, on a clock that wraps. */
static bool at_or_after(uint32_t a, uint32_t b)
{
    return (int32_t)(a - b) >= 0;
}

static uint16_t le16(const uint8_t *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}

uint8_t mc_crc8(uint8_t crc, const uint8_t *data, size_t len)
{
    unsigned c = crc;
    for (size_t i = 0; i < len; i++) {
        c ^= data[i];
        for (int b = 0; b < 8; b++) c = ((c & 0x80u) ? (c << 1) ^ 0x07u : c << 1) & 0xFFu;
    }
    return (uint8_t)c;
}

const char *mc_result_name(mc_result_t r)
{
    switch (r) {
    case MC_OK: return "ok";
    case MC_REFUSED_CRC: return "crc";
    case MC_REFUSED_REGISTER: return "register";
    case MC_REFUSED_LENGTH: return "length";
    case MC_REFUSED_OP: return "op";
    case MC_REFUSED_RANGE: return "range";
    case MC_REFUSED_MIN_OFF: return "min_off";
    case MC_REFUSED_RELAY_CHANGE: return "relay_change";
    }
    return "?";
}

/* ---- the frames ---------------------------------------------------------- */

static bool is_input(uint8_t kind)
{
    return kind == MC_KIND_HIT || kind == MC_KIND_CONTACT;
}

void mc_ident_encode(const mc_config_t *cfg, uint8_t out[MC_IDENT_LEN])
{
    uint8_t classes = 0;
    for (uint8_t i = 0; i < cfg->channel_count && i < MC_MAX_CHANNELS; i++) {
        classes |= is_input(cfg->channels[i].kind) ? 0x01u : 0x00u;
        classes |= cfg->channels[i].kind == MC_KIND_OUTPUT ? 0x02u : 0x00u;
    }
    out[0] = 0x41; /* "AX" */
    out[1] = 0x58;
    out[2] = MC_PROTOCOL_VERSION;
    out[3] = classes;
    out[4] = cfg->channel_count;
    out[5] = (uint8_t)(cfg->model & 0xFFu);
    out[6] = (uint8_t)(cfg->model >> 8);
    out[7] = cfg->hw_rev;
    memcpy(&out[8], cfg->fw, 3);
    memcpy(&out[11], cfg->uid, 4);
    out[15] = mc_crc8(0, out, 15);
}

bool mc_channel_encode(const mc_config_t *cfg, uint8_t index, uint8_t out[MC_CHANNEL_LEN])
{
    if (index >= cfg->channel_count || index >= MC_MAX_CHANNELS) return false;
    const mc_channel_t *c = &cfg->channels[index];
    out[0] = index;
    out[1] = c->kind;
    out[2] = (uint8_t)(c->flags & 0x07u);
    out[3] = c->hint;
    out[4] = c->max_on_s;
    out[5] = c->min_off_s;
    out[6] = 0;
    out[7] = mc_crc8(0, out, 7);
    return true;
}

void mc_status_encode(const mc_status_t *s, uint8_t out[MC_STATUS_LEN])
{
    memset(out, 0, MC_STATUS_LEN);
    out[0] = (uint8_t)(s->flags & 0x7Fu);
    if (s->flags & MC_ST_EVENT) {
        out[1] = s->seq;
        out[2] = (uint8_t)(((unsigned)s->kind << 4) | (s->channel & 0x07u));
        out[3] = s->value;
        out[4] = (uint8_t)(s->age_ms & 0xFFu);
        out[5] = (uint8_t)(s->age_ms >> 8);
    }
    out[6] = s->outputs;
    out[7] = s->armed;
    out[8] = mc_crc8(0, out, 8);
}

/* ---- set-up -------------------------------------------------------------- */

static bool config_valid(const mc_config_t *cfg)
{
    if (cfg->address < MC_FIRST_ADDRESS || cfg->address > MC_LAST_ADDRESS) return false;
    if (cfg->channel_count < 1 || cfg->channel_count > MC_MAX_CHANNELS) return false;
    for (uint8_t i = 0; i < cfg->channel_count; i++) {
        const mc_channel_t *c = &cfg->channels[i];
        if (c->kind == MC_KIND_OUTPUT) {
            uint8_t kind = c->flags & (MC_CH_RELAY | MC_CH_SOLID_STATE);
            if (kind != MC_CH_RELAY && kind != MC_CH_SOLID_STATE) return false;
            if (c->max_on_s == 0) return false;
        } else if (is_input(c->kind)) {
            if (c->max_on_s != 0 || c->min_off_s != 0) return false;
        } else {
            return false;
        }
    }
    return true;
}

static bool is_output_channel(const mc_module_t *m, uint8_t ch)
{
    return ch < m->cfg.channel_count && m->cfg.channels[ch].kind == MC_KIND_OUTPUT;
}

static bool is_input_channel(const mc_module_t *m, uint8_t ch)
{
    return ch < m->cfg.channel_count && is_input(m->cfg.channels[ch].kind);
}

bool mc_init(mc_module_t *m, const mc_config_t *cfg, const mc_ops_t *ops, uint32_t now_ms)
{
    if (m == NULL || cfg == NULL || !config_valid(cfg)) return false;
    bool has_output = false;
    for (uint8_t i = 0; i < cfg->channel_count; i++) {
        has_output |= cfg->channels[i].kind == MC_KIND_OUTPUT;
    }
    if (has_output && (ops == NULL || ops->set_output == NULL)) return false;

    memset(m, 0, sizeof(*m));
    m->cfg = *cfg;
    if (ops != NULL) m->ops = *ops;
    m->now_ms = now_ms;
    m->fresh = true;
    m->lease_ms = MC_LEASE_DEFAULT_100MS * 100u;
    m->pointer = 0xFF; /* no register chosen yet */
    for (uint8_t i = 0; i < cfg->channel_count; i++) {
        const mc_channel_t *c = &cfg->channels[i];
        m->config[i][0] = c->threshold;
        m->config[i][1] = c->holdoff_ms;
        m->config[i][2] = c->debounce_ms;
        /* Off at power-up, whatever the pin did before the firmware ran. */
        if (c->kind == MC_KIND_OUTPUT) m->ops.set_output(m->ops.ctx, i, false);
    }
    return true;
}

/* ---- the outputs and the lease ------------------------------------------- */

static bool level(const mc_output_t *o, uint32_t t)
{
    if (o->mode == MC_MODE_ON) return true;
    if (o->mode == MC_MODE_PATTERN) {
        uint32_t period = o->on_ms + o->off_ms;
        return (uint32_t)(t - o->start_ms) % period < o->on_ms;
    }
    return false;
}

static void output_off(mc_output_t *o, uint32_t t)
{
    if (o->mode != MC_MODE_OFF) {
        o->last_off_ms = t;
        o->has_last_off = true;
    }
    o->mode = MC_MODE_OFF;
    o->has_end = false;
}

static bool any_on(const mc_module_t *m)
{
    for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
        if (m->out[i].mode != MC_MODE_OFF) return true;
    }
    return false;
}

/* How long the channel's load has been off at t: since it was turned off, or since a pattern's
 * last on time ended; UINT32_MAX when it is on or has not been off lately. A relay is not turned
 * on again within 100 ms of either (the reference model checks the first only). */
static uint32_t ms_since_off(const mc_output_t *o, uint32_t t)
{
    if (o->mode == MC_MODE_PATTERN && !level(o, t)) {
        return (uint32_t)(t - o->start_ms) % (o->on_ms + o->off_ms) - o->on_ms;
    }
    if (o->mode == MC_MODE_OFF && o->has_last_off) return (uint32_t)(t - o->last_off_ms);
    return UINT32_MAX;
}

enum { DUE_END, DUE_MAX_ON, DUE_LEASE };

/* Runs the timers up to t, in time order: each output's duration end and max on, and the lease
 * while an output is on. A duration or a max on that ends at the lease's moment goes first, so the
 * output has ended by its duration, not by the lease (section 4). */
static void advance(mc_module_t *m, uint32_t t)
{
    if (!at_or_after(t, m->now_ms)) t = m->now_ms; /* the clock never goes back */
    for (;;) {
        bool found = false;
        uint32_t when = 0;
        int what = DUE_END;
        uint8_t which = 0;
        for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
            const mc_output_t *o = &m->out[i];
            if (o->mode == MC_MODE_OFF) continue;
            uint32_t max_end = o->on_since_ms + (uint32_t)m->cfg.channels[i].max_on_s * 1000u;
            uint32_t cand[2] = {o->end_ms, max_end};
            bool has[2] = {o->has_end, true};
            for (int k = 0; k < 2; k++) {
                if (!has[k] || !at_or_after(t, cand[k])) continue;
                if (!found || !at_or_after(cand[k], when)) {
                    found = true;
                    when = cand[k];
                    what = k == 0 ? DUE_END : DUE_MAX_ON;
                    which = i;
                }
            }
        }
        if (m->has_deadline && any_on(m) && at_or_after(t, m->deadline_ms)) {
            /* The lease loses a tie: it goes only when strictly earlier. */
            if (!found || !at_or_after(m->deadline_ms, when)) {
                found = true;
                when = m->deadline_ms;
                what = DUE_LEASE;
            }
        }
        if (!found) break;
        if (what == DUE_LEASE) {
            for (uint8_t i = 0; i < m->cfg.channel_count; i++) output_off(&m->out[i], when);
            m->lease_expired = true;
            m->has_deadline = false;
        } else if (what == DUE_MAX_ON) {
            output_off(&m->out[which], when);
            m->out[which].has_min_off = true;
            m->out[which].min_off_until_ms =
                when + (uint32_t)m->cfg.channels[which].min_off_s * 1000u;
        } else {
            output_off(&m->out[which], when);
        }
    }
    /* Forget the limits that have passed, so that a clock that wraps (49 days) cannot bring them
     * back. */
    for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
        mc_output_t *o = &m->out[i];
        if (o->has_min_off && at_or_after(t, o->min_off_until_ms)) o->has_min_off = false;
        if (o->has_last_off && (uint32_t)(t - o->last_off_ms) >= MC_RELAY_LEAST_CHANGE_MS) {
            o->has_last_off = false;
        }
    }
    if (m->has_deadline && !any_on(m) && at_or_after(t, m->deadline_ms)) m->has_deadline = false;
    if (m->locating && at_or_after(t, m->locate_until_ms)) m->locating = false;
    m->now_ms = t;
}

/* Hands the outputs' levels at the core's clock to the firmware, those that changed. */
static void sync_outputs(mc_module_t *m)
{
    for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
        if (m->cfg.channels[i].kind != MC_KIND_OUTPUT) continue;
        bool on = level(&m->out[i], m->now_ms);
        uint8_t bit = (uint8_t)(1u << i);
        if (on != ((m->applied & bit) != 0)) {
            m->applied = on ? (uint8_t)(m->applied | bit) : (uint8_t)(m->applied & ~bit);
            m->ops.set_output(m->ops.ctx, i, on);
        }
    }
}

void mc_tick(mc_module_t *m, uint32_t now_ms)
{
    advance(m, now_ms);
    sync_outputs(m);
}

/* ---- COMMAND ------------------------------------------------------------- */

static void drop_events_of(mc_module_t *m, uint8_t channels)
{
    mc_event_t kept[MC_EVENT_QUEUE_LEN];
    uint8_t n = 0;
    for (uint8_t i = 0; i < m->count; i++) {
        const mc_event_t *e = &m->queue[(m->head + i) % MC_EVENT_QUEUE_LEN];
        if (!(channels & (1u << e->channel))) kept[n++] = *e;
    }
    memcpy(m->queue, kept, sizeof(kept[0]) * n);
    m->head = 0;
    m->count = n;
}

/* Checks a COMMAND's arguments (MC_REFUSED_RANGE) and, at this moment, the channel's min off and a
 * relay's 100 ms; then applies it. Nothing changes when it is refused. */
static mc_result_t apply_command(mc_module_t *m, uint8_t op, const uint8_t *a, uint32_t t)
{
    switch (op) {
    case MC_OP_ACK:
        /* A stale or repeated ACK (a lost one sent again) only shows the box the same event again.
         */
        if (m->count > 0 && m->queue[m->head].seq == a[0]) {
            m->head = (uint8_t)((m->head + 1) % MC_EVENT_QUEUE_LEN);
            m->count--;
        }
        return MC_OK;
    case MC_OP_ARM: {
        for (uint8_t i = 0; i < 8; i++) {
            if ((a[0] & (1u << i)) && !is_input_channel(m, i)) return MC_REFUSED_RANGE;
        }
        uint8_t disarmed = (uint8_t)(m->armed & ~a[0]);
        if (disarmed) drop_events_of(m, disarmed);
        m->armed = a[0];
        return MC_OK;
    }
    case MC_OP_OUTPUT: {
        uint8_t ch = a[0], mode = a[1];
        uint16_t dur = le16(&a[2]), on = le16(&a[4]), off = le16(&a[6]);
        if (!is_output_channel(m, ch) || mode > MC_MODE_PATTERN) return MC_REFUSED_RANGE;
        const mc_channel_t *c = &m->cfg.channels[ch];
        bool relay = (c->flags & MC_CH_RELAY) != 0;
        if (mode == MC_MODE_PATTERN) {
            uint16_t least =
                relay ? MC_RELAY_LEAST_PATTERN_10MS : MC_SOLID_STATE_LEAST_PATTERN_10MS;
            if (on < least || off < least) return MC_REFUSED_RANGE;
        }
        mc_output_t *o = &m->out[ch];
        if (mode == MC_MODE_OFF) {
            output_off(o, t); /* an off is never refused */
        } else {
            if (o->has_min_off && !at_or_after(t, o->min_off_until_ms)) return MC_REFUSED_MIN_OFF;
            if (relay && ms_since_off(o, t) < MC_RELAY_LEAST_CHANGE_MS) {
                return MC_REFUSED_RELAY_CHANGE;
            }
            if (o->mode == MC_MODE_OFF) o->on_since_ms = t;
            o->mode = mode;
            o->start_ms = t;
            o->on_ms = (uint32_t)on * 10u;
            o->off_ms = (uint32_t)off * 10u;
            o->has_end = dur != 0;
            o->end_ms = t + (uint32_t)dur * 100u;
        }
        m->has_deadline = true; /* an OUTPUT refreshes the lease */
        m->deadline_ms = t + m->lease_ms;
        m->lease_expired = false;
        return MC_OK;
    }
    case MC_OP_LEASE:
        if (a[0] < MC_LEASE_LEAST_100MS || a[0] > MC_LEASE_MOST_100MS) return MC_REFUSED_RANGE;
        m->lease_ms = (uint32_t)a[0] * 100u;
        m->has_deadline = true;
        m->deadline_ms = t + m->lease_ms;
        m->lease_expired = false;
        return MC_OK;
    case MC_OP_ALL_OFF:
        for (uint8_t i = 0; i < m->cfg.channel_count; i++) output_off(&m->out[i], t);
        return MC_OK;
    case MC_OP_CLEAR_FRESH: m->fresh = false; return MC_OK;
    case MC_OP_LOCATE:
        m->locating = a[0] != 0;
        m->locate_until_ms = t + (uint32_t)a[0] * 1000u;
        return MC_OK;
    case MC_OP_CONFIG:
        if (!is_input_channel(m, a[0]) || a[1] < MC_PARAM_THRESHOLD ||
            a[1] > MC_PARAM_DEBOUNCE_MS) {
            return MC_REFUSED_RANGE;
        }
        m->config[a[0]][a[1] - 1] = le16(&a[2]);
        return MC_OK;
    }
    return MC_REFUSED_OP;
}

/* A COMMAND frame (anything but a register pointer): the CRC first (over the address byte, then
 * every byte but the last), then the register, the op, its length and its arguments, as
 * protocol/expansion-port.md section 2 orders the reasons. */
static mc_result_t take_command(mc_module_t *m, uint32_t t)
{
    size_t n = m->rx_len;
    if (n < 2 || m->crc_prev != m->rx[n > sizeof(m->rx) ? sizeof(m->rx) - 1 : n - 1]) {
        /* A frame longer than rx keeps its last byte in rx's last place (mc_i2c_receive). */
        return MC_REFUSED_CRC;
    }
    if (m->rx[0] != MC_REG_COMMAND) return MC_REFUSED_REGISTER;
    size_t body = n - 1; /* the register, the op and the arguments */
    if (body < 2) return MC_REFUSED_LENGTH;
    uint8_t op = m->rx[1];
    if (op < MC_OP_ACK || op > MC_OP_CONFIG) return MC_REFUSED_OP;
    if (body - 2 != op_args[op]) return MC_REFUSED_LENGTH;
    return apply_command(m, op, &m->rx[2], t);
}

/* The end of a write transaction. */
static void end_write(mc_module_t *m, uint32_t t)
{
    if (!m->writing) return;
    m->writing = false;
    size_t n = m->rx_len;
    if (n == 0) return; /* the box's probe: an address with no byte */
    uint8_t reg = m->rx[0];
    /* A register pointer for the read that follows: not a COMMAND, so it leaves CMD_ERROR alone
     * (else the box's own STATUS poll would clear it before reading it). */
    if (n == 1 && (reg == MC_REG_IDENT || reg == MC_REG_STATUS)) {
        m->pointer = reg;
        return;
    }
    if (n == 2 && reg == MC_REG_CHANNEL) {
        m->pointer = reg;
        m->pointer_index = m->rx[1];
        return;
    }
    advance(m, t);
    mc_result_t r = take_command(m, m->now_ms); /* a write stamped before the clock counts as now */
    m->last_result = r;
    m->cmd_error = r != MC_OK;
    sync_outputs(m);
}

/* ---- STATUS and reads ---------------------------------------------------- */

static bool supply_ok(const mc_module_t *m)
{
    if (m->ops.supply_ok == NULL) return false;
    for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
        if (m->cfg.channels[i].flags & MC_CH_SENSES_SUPPLY) return m->ops.supply_ok(m->ops.ctx);
    }
    return false;
}

uint8_t mc_status_flags(const mc_module_t *m)
{
    uint8_t f = 0;
    if (m->count > 0) f |= MC_ST_EVENT;
    if (m->count > 1) f |= MC_ST_MORE;
    if (m->overflow) f |= MC_ST_OVERFLOW;
    if (supply_ok(m)) f |= MC_ST_SUPPLY_OK;
    if (m->lease_expired) f |= MC_ST_LEASE_EXPIRED;
    if (m->fresh) f |= MC_ST_FRESH;
    if (m->cmd_error) f |= MC_ST_CMD_ERROR;
    return f;
}

static void build_status(mc_module_t *m, uint8_t out[MC_STATUS_LEN])
{
    mc_status_t s = {0};
    s.flags = mc_status_flags(m);
    if (m->count > 0) {
        const mc_event_t *e = &m->queue[m->head];
        uint32_t age = at_or_after(m->now_ms, e->t_ms) ? m->now_ms - e->t_ms : 0;
        s.seq = e->seq;
        s.channel = e->channel;
        s.kind = e->kind;
        s.value = e->value;
        s.age_ms = age > 0xFFFFu ? 0xFFFFu : (uint16_t)age;
    }
    s.outputs = mc_outputs(m);
    s.armed = m->armed;
    mc_status_encode(&s, out);
}

/* The read's bytes, made at its address match so that they hold together (and the age is now's). */
static void begin_read(mc_module_t *m, uint32_t t)
{
    advance(m, t);
    sync_outputs(m);
    m->reading = true;
    m->tx_pos = 0;
    m->tx_len = 0;
    m->tx_status_overflow = false;
    switch (m->pointer) {
    case MC_REG_IDENT:
        mc_ident_encode(&m->cfg, m->tx);
        m->tx_len = MC_IDENT_LEN;
        break;
    case MC_REG_CHANNEL:
        if (mc_channel_encode(&m->cfg, m->pointer_index, m->tx)) m->tx_len = MC_CHANNEL_LEN;
        break;
    case MC_REG_STATUS:
        build_status(m, m->tx);
        m->tx_len = MC_STATUS_LEN;
        m->tx_status_overflow = m->overflow;
        break;
    default: break; /* no register chosen: 0xFF, as an empty bus */
    }
}

static void end_read(mc_module_t *m)
{
    if (!m->reading) return;
    m->reading = false;
    /* OVERFLOW means "since the last report": a STATUS that carried it, read to its CRC, reported
     * it. */
    if (m->tx_status_overflow && m->tx_pos >= MC_STATUS_LEN) m->overflow = false;
    m->tx_status_overflow = false;
}

/* ---- the I2C target ------------------------------------------------------ */

void mc_i2c_start(mc_module_t *m, bool read, uint32_t now_ms)
{
    end_write(m, now_ms); /* a repeated start ends the write before it */
    end_read(m);
    if (read) {
        begin_read(m, now_ms);
    } else {
        m->writing = true;
        m->rx_len = 0;
        uint8_t address_byte = (uint8_t)(m->cfg.address << 1);
        m->crc_prev = 0;
        m->crc_all = mc_crc8(0, &address_byte, 1);
    }
}

void mc_i2c_receive(mc_module_t *m, uint8_t byte)
{
    if (!m->writing) return;
    m->crc_prev = m->crc_all;
    m->crc_all = mc_crc8(m->crc_all, &byte, 1);
    /* Keep the first bytes; a longer frame keeps its newest byte in the last place, for its CRC. */
    if (m->rx_len < sizeof(m->rx)) {
        m->rx[m->rx_len] = byte;
    } else {
        m->rx[sizeof(m->rx) - 1] = byte;
    }
    if (m->rx_len < SIZE_MAX) m->rx_len++;
}

uint8_t mc_i2c_request(mc_module_t *m)
{
    if (!m->reading || m->tx_pos >= m->tx_len) {
        if (m->reading && m->tx_pos < 0xFF) m->tx_pos++;
        return 0xFF;
    }
    return m->tx[m->tx_pos++];
}

void mc_i2c_stop(mc_module_t *m, uint32_t now_ms)
{
    end_write(m, now_ms);
    end_read(m);
}

mc_result_t mc_write(mc_module_t *m, const uint8_t *bytes, size_t len, uint32_t now_ms)
{
    mc_i2c_start(m, false, now_ms);
    for (size_t i = 0; i < len; i++) mc_i2c_receive(m, bytes[i]);
    bool command = !(len == 1 && (bytes[0] == MC_REG_IDENT || bytes[0] == MC_REG_STATUS)) &&
                   !(len == 2 && bytes[0] == MC_REG_CHANNEL) && len > 0;
    mc_i2c_stop(m, now_ms);
    return command ? m->last_result : MC_OK;
}

void mc_read(mc_module_t *m, uint8_t *out, size_t len, uint32_t now_ms)
{
    mc_i2c_start(m, true, now_ms);
    for (size_t i = 0; i < len; i++) out[i] = mc_i2c_request(m);
    mc_i2c_stop(m, now_ms);
}

/* ---- inputs -------------------------------------------------------------- */

bool mc_event(mc_module_t *m, uint8_t channel, uint8_t kind, uint8_t value, uint32_t t_ms)
{
    if (!is_input_channel(m, channel)) return false;
    uint8_t ck = m->cfg.channels[channel].kind;
    bool fits = ck == MC_KIND_HIT ? kind == MC_EVENT_HIT
                                  : (kind == MC_EVENT_CLOSED || kind == MC_EVENT_OPENED);
    if (!fits) return false;
    if (!(m->armed & (1u << channel))) return false;
    if (m->count >= MC_EVENT_QUEUE_LEN) {
        /* The oldest stays shown (the box may be acknowledging it); the newest is dropped and takes
         * no sequence number, so the box sees no gap, only OVERFLOW. */
        m->overflow = true;
        return false;
    }
    mc_event_t *e = &m->queue[(m->head + m->count) % MC_EVENT_QUEUE_LEN];
    e->t_ms = t_ms;
    e->seq = m->next_seq++;
    e->channel = channel;
    e->kind = (uint8_t)kind;
    e->value = value;
    m->count++;
    return true;
}

/* ---- reading back -------------------------------------------------------- */

uint8_t mc_outputs(const mc_module_t *m)
{
    uint8_t bits = 0;
    for (uint8_t i = 0; i < m->cfg.channel_count; i++) {
        if (level(&m->out[i], m->now_ms)) bits |= (uint8_t)(1u << i);
    }
    return bits;
}

uint8_t mc_armed(const mc_module_t *m)
{
    return m->armed;
}

uint16_t mc_config_value(const mc_module_t *m, uint8_t channel, uint8_t parameter)
{
    if (!is_input_channel(m, channel) || parameter < MC_PARAM_THRESHOLD ||
        parameter > MC_PARAM_DEBOUNCE_MS) {
        return 0;
    }
    return m->config[channel][parameter - 1];
}

bool mc_locating(mc_module_t *m, uint32_t now_ms)
{
    if (m->locating && at_or_after(now_ms, m->locate_until_ms)) m->locating = false;
    return m->locating;
}

mc_result_t mc_last_result(const mc_module_t *m)
{
    return m->last_result;
}
