/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port's driver, the box's side (expansion.h; protocol/expansion-port.md).
 */
#include "expansion.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static const char *const HINT_FUNCTION[EXP_HINT_COUNT] = {NULL,    "siren", "strobe",
                                                          "smoke", "light", "horn"};

/* ---- Frames ------------------------------------------------------------------------------ */

uint8_t expansion_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) crc = (uint8_t)((crc & 0x80) ? (crc << 1) ^ 0x07 : crc << 1);
    }
    return crc;
}

static const char *check_read(const uint8_t *f, size_t len, size_t want)
{
    if (f == NULL || len != want) return "length";
    if (expansion_crc8(f, want - 1) != f[want - 1]) return "crc";
    return NULL;
}

const char *expansion_parse_ident(const uint8_t *f, size_t len, exp_ident_t *out)
{
    const char *why = check_read(f, len, EXP_IDENT_LEN);
    if (why != NULL) return why;
    if (f[0] != EXP_MAGIC0 || f[1] != EXP_MAGIC1) return "magic";
    if (f[2] != EXP_PROTOCOL) return "version";
    if ((f[3] & (EXP_CLASS_INPUTS | EXP_CLASS_OUTPUTS)) == 0) return "classes";
    if (f[4] < 1 || f[4] > EXP_CHANNELS_MAX) return "channels";
    if (out != NULL) {
        out->inputs = (f[3] & EXP_CLASS_INPUTS) != 0;
        out->outputs = (f[3] & EXP_CLASS_OUTPUTS) != 0;
        out->channels = f[4];
        out->model = (uint16_t)(f[5] | (f[6] << 8));
        out->hw = f[7];
        memcpy(out->fw, f + 8, 3);
        memcpy(out->uid, f + 11, 4);
    }
    return NULL;
}

const char *expansion_parse_channel(const uint8_t *f, size_t len, int index, exp_channel_t *out)
{
    const char *why = check_read(f, len, EXP_CHANNEL_LEN);
    if (why != NULL) return why;
    if (f[0] != index || f[0] >= EXP_CHANNELS_MAX) return "index";
    if (f[1] != EXP_KIND_HIT && f[1] != EXP_KIND_OUTPUT) return "kind";
    if (f[1] == EXP_KIND_OUTPUT && f[4] == 0) return "max_on";
    if (out != NULL) {
        out->index = f[0];
        out->kind = f[1];
        out->flags = f[2] & (EXP_CH_RELAY | EXP_CH_SOLID_STATE | EXP_CH_SENSES);
        out->hint = f[3] < EXP_HINT_COUNT ? f[3] : 0;
        out->max_on_s = f[4];
        out->min_off_s = f[5];
    }
    return NULL;
}

const char *expansion_parse_status(const uint8_t *f, size_t len, int channels, exp_status_t *out)
{
    const char *why = check_read(f, len, EXP_STATUS_LEN);
    if (why != NULL) return why;
    bool event = (f[0] & EXP_ST_EVENT) != 0;
    uint8_t ch = f[2] & 0x07, kind = f[2] >> 4;
    if (event && ch >= channels) return "channel";
    if (event && (kind < EXP_EV_HIT || kind > EXP_EV_OPENED)) return "event_kind";
    if (out != NULL) {
        memset(out, 0, sizeof(*out));
        out->flags = f[0] & 0x7F;
        out->event = event;
        if (event) {
            out->seq = f[1];
            out->channel = ch;
            out->kind = kind;
            out->value = f[3];
            out->age_ms = (uint16_t)(f[4] | (f[5] << 8));
        }
        out->outputs = f[6];
        out->armed = f[7];
    }
    return NULL;
}

static size_t put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)(v >> 8);
    return 2;
}

size_t expansion_encode_command(const exp_command_t *c, uint8_t addr, uint8_t *out, size_t cap)
{
    uint8_t buf[1 + EXP_COMMAND_MAX];
    size_t n = 0;
    buf[n++] = (uint8_t)(addr << 1); /* the address byte as sent: covered by the CRC */
    buf[n++] = EXP_REG_COMMAND;
    buf[n++] = c->op;
    switch (c->op) {
    case EXP_OP_ACK: buf[n++] = c->seq; break;
    case EXP_OP_ARM: buf[n++] = c->armed; break;
    case EXP_OP_OUTPUT:
        buf[n++] = c->channel;
        buf[n++] = c->mode;
        n += put16(buf + n, c->duration_100ms);
        n += put16(buf + n, c->on_10ms);
        n += put16(buf + n, c->off_10ms);
        break;
    case EXP_OP_LEASE: buf[n++] = c->lease_100ms; break;
    case EXP_OP_ALL_OFF:
    case EXP_OP_CLEAR_FRESH: break;
    case EXP_OP_LOCATE: buf[n++] = c->seconds; break;
    case EXP_OP_CONFIG:
        buf[n++] = c->channel;
        buf[n++] = c->parameter;
        n += put16(buf + n, c->value);
        break;
    default: return 0;
    }
    buf[n] = expansion_crc8(buf, n);
    n++;
    if (cap < n - 1) return 0;
    memcpy(out, buf + 1, n - 1);
    return n - 1;
}

void expansion_model_name(uint16_t model, char *out, size_t cap)
{
    if (model == 0x0001) {
        snprintf(out, cap, "target");
    } else if (model == 0x0002) {
        snprintf(out, cap, "out4");
    } else {
        snprintf(out, cap, "m%04x", (unsigned)model);
    }
}

/* ---- Helpers ---------------------------------------------------------------------------- */

static void say(expansion_t *e, const char *fmt, ...)
{
    if (e->ops.log == NULL) return;
    char line[128];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    e->ops.log(e->ops.ctx, line);
}

static void emit(expansion_t *e, const exp_event_t *ev)
{
    if (e->ops.event != NULL) e->ops.event(e->ops.ctx, ev);
}

static bool due(uint32_t now, uint32_t at)
{
    return (int32_t)(now - at) >= 0;
}

static exp_module_t *find(expansion_t *e, uint8_t addr)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        if (e->mod[i].used && e->mod[i].addr == addr) return &e->mod[i];
    }
    return NULL;
}

const exp_module_t *expansion_module(const expansion_t *e, uint8_t addr)
{
    return find((expansion_t *)e, addr);
}

int expansion_module_count(const expansion_t *e)
{
    int n = 0;
    for (int i = 0; i < EXP_MODULES_MAX; i++) n += e->mod[i].used ? 1 : 0;
    return n;
}

static uint32_t poll_period(const exp_module_t *m)
{
    return m->inputs != 0 ? EXP_POLL_INPUT_MS : EXP_POLL_OUTPUT_MS;
}

static bool write_cmd(expansion_t *e, exp_module_t *m, uint8_t addr, const exp_command_t *c)
{
    uint8_t buf[EXP_COMMAND_MAX];
    size_t n = expansion_encode_command(c, addr, buf, sizeof(buf));
    if (n == 0) return false;
    int r = e->bus.write(e->bus.ctx, addr, buf, n);
    if (m != NULL) {
        m->writes++;
        if (r != EXP_BUS_OK) m->write_errors++;
        if (c->op == EXP_OP_OUTPUT || c->op == EXP_OP_LEASE) {
            /* Counted as written either way: a lost refresh leaves two more before the lease
             * runs out, and the next poll repairs a lost OUTPUT. */
            m->lease_known = true;
            m->lease_ms = e->now;
        }
    }
    return r == EXP_BUS_OK;
}

static bool simple_cmd(expansion_t *e, exp_module_t *m, uint8_t addr, uint8_t op)
{
    exp_command_t c = {0};
    c.op = op;
    return write_cmd(e, m, addr, &c);
}

static int read_reg(expansion_t *e, uint8_t addr, const uint8_t *ptr, size_t ptr_len, uint8_t *in,
                    size_t in_len)
{
    return e->bus.write_read(e->bus.ctx, addr, ptr, ptr_len, in, in_len);
}

/* ---- Capability ids (EXP-19) ------------------------------------------------------------- */

static bool cap_taken(const expansion_t *e, const char *id)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        const exp_module_t *m = &e->mod[i];
        if (!m->used) continue;
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
            if ((m->usable & (1u << c)) && strcmp(m->cap[c], id) == 0) return true;
        }
    }
    return false;
}

/* A hit channel is hit, then hit.2; an output its hint's function or out.<channel + 1>, then
 * <function>.2. Given when the module is added and kept while it stays. */
static void name_caps(expansion_t *e, exp_module_t *m)
{
    for (int c = 0; c < m->ident.channels; c++) {
        m->cap[c][0] = '\0';
        if (!(m->usable & (1u << c))) continue;
        char base[EXP_CAP_ID_MAX + 1];
        if (m->ch[c].kind == EXP_KIND_HIT) {
            snprintf(base, sizeof(base), "hit");
        } else if (HINT_FUNCTION[m->ch[c].hint] != NULL) {
            snprintf(base, sizeof(base), "%s", HINT_FUNCTION[m->ch[c].hint]);
        } else {
            snprintf(base, sizeof(base), "out.%d", c + 1);
        }
        char id[EXP_CAP_ID_MAX + 1];
        snprintf(id, sizeof(id), "%s", base);
        for (int k = 2; cap_taken(e, id) && k < 100; k++) {
            snprintf(id, sizeof(id), "%.19s.%d", base, k);
        }
        memcpy(m->cap[c], id, sizeof(id));
    }
}

size_t expansion_module_text(const exp_module_t *m, char *out, size_t cap)
{
    char model[8], line[EXP_MODULES_TEXT_MAX + 1];
    expansion_model_name(m->ident.model, model, sizeof(model));
    int n = snprintf(line, sizeof(line), "%02x:%s/%u.%u.%u:", m->addr, model, m->ident.fw[0],
                     m->ident.fw[1], m->ident.fw[2]);
    bool any = false;
    for (int c = 0; c < m->ident.channels && n > 0 && (size_t)n < sizeof(line); c++) {
        if (!(m->usable & (1u << c))) continue;
        n += snprintf(line + n, sizeof(line) - (size_t)n, "%s%s", any ? "," : "", m->cap[c]);
        any = true;
    }
    if (!any || n <= 0 || (size_t)n >= sizeof(line) || (size_t)n >= cap) {
        if (cap > 0) out[0] = '\0';
        return 0;
    }
    memcpy(out, line, (size_t)n + 1);
    return (size_t)n;
}

size_t expansion_modules_text(const expansion_t *e, char *out, size_t cap)
{
    if (cap == 0) return 0;
    out[0] = '\0';
    size_t len = 0;
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        const exp_module_t *m = expansion_module(e, (uint8_t)a);
        if (m == NULL) continue;
        char entry[EXP_MODULES_TEXT_MAX + 1];
        size_t n = expansion_module_text(m, entry, sizeof(entry));
        if (n == 0) continue;
        size_t need = n + (len > 0 ? 1 : 0);
        if (len + need > EXP_MODULES_TEXT_MAX || len + need + 1 > cap) continue; /* whole only */
        if (len > 0) out[len++] = ';';
        memcpy(out + len, entry, n + 1);
        len += n;
    }
    return len;
}

/* ---- Discovery and loss (EXP-14) --------------------------------------------------------- */

static int tried_read(expansion_t *e, uint8_t addr, const uint8_t *ptr, size_t ptr_len, uint8_t *in,
                      size_t in_len, const char *(*check)(const uint8_t *, size_t, int, void *),
                      int arg, void *out, const char **why)
{
    *why = "no_answer";
    for (int t = 0; t < EXP_DISCOVERY_TRIES; t++) {
        if (read_reg(e, addr, ptr, ptr_len, in, in_len) != EXP_BUS_OK) continue;
        *why = check(in, in_len, arg, out);
        if (*why == NULL) return 0;
        if (strcmp(*why, "crc") != 0 && strcmp(*why, "length") != 0) return -1; /* final */
    }
    return -1;
}

static const char *check_ident(const uint8_t *f, size_t len, int arg, void *out)
{
    (void)arg;
    return expansion_parse_ident(f, len, (exp_ident_t *)out);
}

static const char *check_channel(const uint8_t *f, size_t len, int arg, void *out)
{
    return expansion_parse_channel(f, len, arg, (exp_channel_t *)out);
}

/* Reads a module's IDENT and channels into m (not yet added). False when the IDENT is refused
 * or unanswered, or no channel is usable. */
static bool read_module(expansion_t *e, uint8_t addr, exp_module_t *m)
{
    memset(m, 0, sizeof(*m));
    m->addr = addr;
    const uint8_t ptr = EXP_REG_IDENT;
    const char *why;
    if (tried_read(e, addr, &ptr, 1, m->ident_raw, EXP_IDENT_LEN, check_ident, 0, &m->ident,
                   &why) != 0) {
        say(e, "expansion: 0x%02X: IDENT refused (%s)", addr, why);
        return false;
    }
    for (int c = 0; c < m->ident.channels; c++) {
        uint8_t p[2] = {EXP_REG_CHANNEL, (uint8_t)c}, f[EXP_CHANNEL_LEN];
        if (tried_read(e, addr, p, 2, f, sizeof(f), check_channel, c, &m->ch[c], &why) != 0) {
            say(e, "expansion: 0x%02X: channel %d refused (%s)", addr, c, why);
            continue;
        }
        m->usable |= (uint8_t)(1u << c);
        if (m->ch[c].kind == EXP_KIND_HIT) m->inputs |= (uint8_t)(1u << c);
        if (m->ch[c].kind == EXP_KIND_OUTPUT) m->outputs |= (uint8_t)(1u << c);
    }
    if (m->usable == 0) {
        say(e, "expansion: 0x%02X: no usable channel, not added", addr);
        return false;
    }
    return true;
}

static exp_module_t *free_slot(expansion_t *e)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        if (!e->mod[i].used) return &e->mod[i];
    }
    return NULL;
}

/* A module answered at addr: read it, then (unless boot already did) ALL_OFF, then CLEAR_FRESH,
 * and add it. */
static bool discover(expansion_t *e, uint8_t addr, bool boot)
{
    exp_module_t *slot = free_slot(e);
    if (slot == NULL) return false;
    exp_module_t m;
    if (!read_module(e, addr, &m)) return false;
    if (!boot) simple_cmd(e, &m, addr, EXP_OP_ALL_OFF);
    simple_cmd(e, &m, addr, EXP_OP_CLEAR_FRESH);
    m.lease_known = false;
    m.used = true;
    m.next_poll = e->now + poll_period(&m);
    *slot = m;
    name_caps(e, slot);
    expansion_module_text(slot, e->text, sizeof(e->text));
    say(e, "expansion: 0x%02X added: %s", addr, e->text);
    exp_event_t ev = {0};
    ev.type = EXP_EVT_ADDED;
    ev.address = addr;
    ev.text = e->text;
    emit(e, &ev);
    return true;
}

static void lose(expansion_t *e, exp_module_t *m, const char *reason)
{
    expansion_module_text(m, e->text, sizeof(e->text));
    uint8_t addr = m->addr;
    memset(m, 0, sizeof(*m)); /* its outputs count as off: its lease has run out */
    say(e, "expansion: 0x%02X lost (%s)", addr, reason);
    exp_event_t ev = {0};
    ev.type = EXP_EVT_LOST;
    ev.address = addr;
    ev.reason = reason;
    ev.text = e->text;
    emit(e, &ev);
}

static void failed_read(expansion_t *e, exp_module_t *m)
{
    m->read_errors++;
    if (++m->fails >= EXP_LOST_AFTER) lose(e, m, "no_answer");
}

void expansion_init(expansion_t *e, const exp_bus_t *bus, const exp_ops_t *ops)
{
    memset(e, 0, sizeof(*e));
    e->bus = *bus;
    if (ops != NULL) e->ops = *ops;
    e->probe_next = EXP_ADDR_FIRST;
    e->reprobe = -1;
}

void expansion_start(expansion_t *e, uint32_t now_ms)
{
    e->now = now_ms;
    bool answered[EXP_ADDR_COUNT] = {false};
    /* ALL_OFF to every module before anything else (EXP-14, EXP-29). */
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        if (!e->bus.probe(e->bus.ctx, (uint8_t)a)) continue;
        answered[a - EXP_ADDR_FIRST] = true;
        simple_cmd(e, NULL, (uint8_t)a, EXP_OP_ALL_OFF);
    }
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        if (answered[a - EXP_ADDR_FIRST]) discover(e, (uint8_t)a, true);
    }
    e->started = true;
    e->next_probe = now_ms + EXP_PROBE_STEP_MS;
}

/* Hot-plug: one address every EXP_PROBE_STEP_MS in turn, so each empty address is probed every
 * EXP_PROBE_MS (an address with a module is skipped, its turn left unused). */
static void probe_one(expansion_t *e)
{
    if (e->reprobe >= 0) {
        uint8_t a = (uint8_t)e->reprobe;
        e->reprobe = -1;
        if (find(e, a) == NULL && e->bus.probe(e->bus.ctx, a)) discover(e, a, false);
    }
    if (!due(e->now, e->next_probe)) return;
    e->next_probe = e->now + EXP_PROBE_STEP_MS;
    uint8_t a = e->probe_next;
    e->probe_next = a >= EXP_ADDR_LAST ? EXP_ADDR_FIRST : (uint8_t)(a + 1);
    if (find(e, a) != NULL || expansion_module_count(e) >= EXP_MODULES_MAX) return;
    if (e->bus.probe(e->bus.ctx, a)) discover(e, a, false);
}

/* ---- Outputs (EXP-11, EXP-12, EXP-13) --------------------------------------------------- */

/* When the desired state ends on the box's clock: its own end, or the module's max on. 0: no
 * end. */
static uint32_t end_of(const exp_module_t *m, int c, const exp_output_t *o)
{
    uint32_t end = o->want.until_ms;
    if (o->on_known) {
        uint32_t max_end = o->on_since + (uint32_t)m->ch[c].max_on_s * 1000u;
        if (end == 0 || (int32_t)(max_end - end) < 0) end = max_end;
    }
    return end;
}

/* Turns a desired state that has run its time to off (no write: the module's own timer ends
 * it). After the module's max on, the box holds new starts for its min off. */
static void expire(exp_module_t *m, int c, uint32_t now)
{
    exp_output_t *o = &m->out[c];
    if (o->want.mode == EXP_MODE_OFF) return;
    uint32_t end = end_of(m, c, o);
    if (end == 0 || !due(now, end)) return;
    bool by_max_on = o->on_known && end == o->on_since + (uint32_t)m->ch[c].max_on_s * 1000u &&
                     (o->want.until_ms == 0 || (int32_t)(o->want.until_ms - end) > 0);
    if (by_max_on && m->ch[c].min_off_s > 0) {
        o->min_off = true;
        o->min_off_until = end + (uint32_t)m->ch[c].min_off_s * 1000u;
    }
    o->want.mode = EXP_MODE_OFF;
    o->on_known = false;
    o->dirty = false;
}

static bool active(const exp_output_t *o)
{
    return o->want.mode != EXP_MODE_OFF;
}

static uint16_t units(uint32_t ms, uint32_t unit)
{
    uint32_t u = (ms + unit - 1) / unit;
    return (uint16_t)(u > 0xFFFF ? 0xFFFF : u);
}

/* Sends channel c's desired state: on or pattern with what is left, rounded up to 100 ms. */
static void send_output(expansion_t *e, exp_module_t *m, int c)
{
    exp_output_t *o = &m->out[c];
    exp_command_t cmd = {0};
    cmd.op = EXP_OP_OUTPUT;
    cmd.channel = (uint8_t)c;
    cmd.mode = o->want.mode;
    if (o->want.mode != EXP_MODE_OFF) {
        if (o->want.until_ms != 0) {
            uint32_t left = o->want.until_ms - e->now;
            cmd.duration_100ms = units(left, 100);
        }
        if (o->want.mode == EXP_MODE_PATTERN) {
            cmd.on_10ms = units(o->want.on_ms, 10);
            cmd.off_10ms = units(o->want.off_ms, 10);
        }
        if (!o->on_known) {
            o->on_known = true;
            o->on_since = e->now;
        }
        uint32_t max_on = (uint32_t)m->ch[c].max_on_s * 1000u;
        uint32_t run = cmd.duration_100ms != 0 ? (uint32_t)cmd.duration_100ms * 100u : max_on;
        o->ends_known = true;
        o->ends_at = e->now + (run < max_on ? run : max_on);
    } else {
        o->off_known = true;
        o->off_ms_at = e->now;
        o->on_known = false;
        o->ends_known = false;
    }
    o->sent_ms = e->now;
    o->dirty = false;
    write_cmd(e, m, m->addr, &cmd);
}

/* A relay channel turns on again no sooner than 100 ms after its last off (the module refuses
 * it): such a start waits. */
static bool may_send(const expansion_t *e, const exp_module_t *m, int c)
{
    const exp_output_t *o = &m->out[c];
    if (o->want.mode == EXP_MODE_OFF || !(m->ch[c].flags & EXP_CH_RELAY) || !o->off_known) {
        return true;
    }
    return e->now - o->off_ms_at >= EXP_RELAY_CHANGE_MS;
}

/* What a pattern shows now, or -1 too close to an edge to say. */
static int pattern_level(const exp_output_t *o, uint32_t now)
{
    uint32_t on = (uint32_t)units(o->want.on_ms, 10) * 10u;
    uint32_t period = on + (uint32_t)units(o->want.off_ms, 10) * 10u;
    if (period == 0) return -1;
    uint32_t at = (now - o->sent_ms) % period;
    uint32_t to_edge = at < period - at ? at : period - at;
    uint32_t to_off = at > on ? at - on : on - at;
    if (to_off < to_edge) to_edge = to_off;
    if (to_edge < EXP_PATTERN_EDGE_MS) return -1;
    return at < on ? 1 : 0;
}

static void reconcile_outputs(expansion_t *e, exp_module_t *m, uint8_t shown)
{
    for (int c = 0; c < m->ident.channels; c++) {
        if (!(m->outputs & (1u << c))) continue;
        exp_output_t *o = &m->out[c];
        expire(m, c, e->now);
        if (o->dirty) continue; /* goes out with the pending writes */
        bool is_on = (shown & (1u << c)) != 0;
        bool resend = false;
        if (o->want.mode == EXP_MODE_ON) {
            resend = !is_on;
        } else if (o->want.mode == EXP_MODE_PATTERN) {
            int level = pattern_level(o, e->now);
            resend = level >= 0 && (level == 1) != is_on;
        } else {
            /* Off, unless what the box sent last is still running out on the module's own
             * timer (its duration was rounded up to 100 ms): that ends by itself. */
            resend = is_on && !(o->ends_known && !due(e->now, o->ends_at));
        }
        if (resend && may_send(e, m, c)) {
            m->resends++;
            send_output(e, m, c);
        }
    }
}

static void send_pending(expansion_t *e, exp_module_t *m)
{
    if (m->all_off_pending) {
        m->all_off_pending = false;
        simple_cmd(e, m, m->addr, EXP_OP_ALL_OFF);
    }
    for (int c = 0; c < m->ident.channels; c++) {
        if (!(m->outputs & (1u << c))) continue;
        expire(m, c, e->now);
        if (m->out[c].dirty && may_send(e, m, c)) send_output(e, m, c);
    }
}

static void refresh_lease(expansion_t *e, exp_module_t *m)
{
    bool any = false;
    for (int c = 0; c < m->ident.channels; c++) {
        if (!(m->outputs & (1u << c))) continue;
        expire(m, c, e->now);
        any = any || active(&m->out[c]);
    }
    if (!any) return;
    if (m->lease_known && e->now - m->lease_ms < EXP_LEASE_REFRESH_MS) return;
    exp_command_t c = {0};
    c.op = EXP_OP_LEASE;
    c.lease_100ms = EXP_LEASE_100MS;
    write_cmd(e, m, m->addr, &c);
}

exp_result_t expansion_output(expansion_t *e, uint8_t addr, uint8_t channel,
                              const exp_desired_t *want, uint32_t now_ms)
{
    exp_module_t *m = find(e, addr);
    if (m == NULL || channel >= EXP_CHANNELS_MAX || !(m->outputs & (1u << channel))) {
        return EXP_NO_SUCH;
    }
    if (want->mode > EXP_MODE_PATTERN) return EXP_BAD_ARGS;
    exp_output_t *o = &m->out[channel];
    expire(m, channel, now_ms);
    if (want->mode == EXP_MODE_PATTERN) {
        uint32_t floor =
            (m->ch[channel].flags & EXP_CH_RELAY) ? EXP_RELAY_PATTERN_MS : EXP_SOLID_PATTERN_MS;
        if (want->on_ms < floor || want->off_ms < floor || want->on_ms > EXP_PATTERN_MAX_MS ||
            want->off_ms > EXP_PATTERN_MAX_MS) {
            return EXP_BAD_ARGS;
        }
    }
    if (want->mode != EXP_MODE_OFF) {
        if (want->until_ms != 0 && !due(want->until_ms, now_ms + 1)) return EXP_BAD_ARGS;
        if (o->min_off && !due(now_ms, o->min_off_until)) return EXP_TOO_SOON;
        o->min_off = false;
        if (o->want.mode == EXP_MODE_OFF) o->on_known = false; /* a new start */
    } else if (o->want.mode == EXP_MODE_OFF && !o->dirty) {
        return EXP_OK; /* already off */
    }
    o->want = *want;
    o->dirty = true;
    return EXP_OK;
}

void expansion_all_off(expansion_t *e)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        exp_module_t *m = &e->mod[i];
        if (!m->used || m->outputs == 0) continue;
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
            exp_output_t *o = &m->out[c];
            if (active(o)) {
                o->off_known = true;
                o->off_ms_at = e->now;
            }
            o->want.mode = EXP_MODE_OFF;
            o->dirty = false;
            o->on_known = false;
            o->ends_known = false;
        }
        m->all_off_pending = true;
    }
}

exp_result_t expansion_arm(expansion_t *e, uint8_t addr, uint8_t bitmap)
{
    exp_module_t *m = find(e, addr);
    if (m == NULL || m->inputs == 0) return EXP_NO_SUCH;
    m->armed_want = bitmap & m->inputs;
    return EXP_OK;
}

bool expansion_set_cap(expansion_t *e, uint8_t addr, uint8_t channel, const char *id)
{
    exp_module_t *m = find(e, addr);
    if (m == NULL || channel >= EXP_CHANNELS_MAX || !(m->usable & (1u << channel)) || id == NULL ||
        strlen(id) > EXP_CAP_ID_MAX || strcmp(m->cap[channel], id) == 0) {
        return false;
    }
    snprintf(m->cap[channel], sizeof(m->cap[channel]), "%s", id);
    return true;
}

bool expansion_find(const expansion_t *e, const char *cap, uint8_t *addr, uint8_t *channel)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        const exp_module_t *m = &e->mod[i];
        if (!m->used) continue;
        for (int c = 0; c < m->ident.channels; c++) {
            if ((m->usable & (1u << c)) && strcmp(m->cap[c], cap) == 0) {
                if (addr != NULL) *addr = m->addr;
                if (channel != NULL) *channel = (uint8_t)c;
                return true;
            }
        }
    }
    return false;
}

void expansion_backend_drive(void *ctx, bool on, bool live, uint32_t now_ms)
{
    (void)live;
    exp_out_ref_t *r = (exp_out_ref_t *)ctx;
    const exp_module_t *m = expansion_module(r->exp, r->addr);
    if (m == NULL || r->channel >= EXP_CHANNELS_MAX) return;
    bool is_on = m->out[r->channel].want.mode != EXP_MODE_OFF;
    if (on == is_on) return;
    exp_desired_t want = {on ? EXP_MODE_ON : EXP_MODE_OFF, 0, 0, 0};
    expansion_output(r->exp, r->addr, r->channel, &want, now_ms);
}

/* ---- Polling ---------------------------------------------------------------------------- */

/* FRESH: the module restarted. Its IDENT is read again: another module there is the old one
 * lost and the new one found. Then its flag is cleared and its state sent again. False when
 * the module was dropped or the IDENT could not be read (the next poll tries again). */
static bool restarted(expansion_t *e, exp_module_t *m)
{
    uint8_t raw[EXP_IDENT_LEN];
    const uint8_t ptr = EXP_REG_IDENT;
    exp_ident_t id;
    const char *why;
    if (tried_read(e, m->addr, &ptr, 1, raw, sizeof(raw), check_ident, 0, &id, &why) != 0 &&
        (strcmp(why, "no_answer") == 0 || strcmp(why, "crc") == 0 || strcmp(why, "length") == 0)) {
        failed_read(e, m);
        return false;
    }
    if (why != NULL || memcmp(raw, m->ident_raw, sizeof(raw)) != 0) {
        uint8_t addr = m->addr;
        lose(e, m, "bad_ident");
        e->reprobe = addr;
        return false;
    }
    m->restarts++;
    m->have_seq = false; /* its sequence numbers start again */
    m->lease_known = false;
    bool any = false;
    for (int c = 0; c < m->ident.channels; c++) {
        if (!(m->outputs & (1u << c))) continue;
        expire(m, c, e->now);
        exp_output_t *o = &m->out[c];
        any = any || active(o);
        o->on_known = false; /* its max on starts again with the resend */
    }
    if (!any && m->outputs != 0) simple_cmd(e, m, m->addr, EXP_OP_ALL_OFF);
    simple_cmd(e, m, m->addr, EXP_OP_CLEAR_FRESH);
    say(e, "expansion: 0x%02X restarted", m->addr);
    return true;
}

static void note_flags(expansion_t *e, exp_module_t *m, uint8_t flags)
{
    uint8_t rising = flags & (uint8_t)~m->last_flags;
    m->last_flags = flags;
    if (flags & EXP_ST_CMD_ERROR) {
        m->cmd_errors++;
        if (rising & EXP_ST_CMD_ERROR) say(e, "expansion: 0x%02X refused a write", m->addr);
    }
    if (rising & EXP_ST_LEASE_EXPIRED) {
        m->lease_expiries++;
        say(e, "expansion: 0x%02X: its lease ran out", m->addr);
    }
    if (flags & EXP_ST_OVERFLOW) {
        m->overflows++;
        exp_event_t ev = {0};
        ev.type = EXP_EVT_OVERFLOW;
        ev.address = m->addr;
        emit(e, &ev);
    }
}

static void take_event(expansion_t *e, exp_module_t *m, const exp_status_t *st)
{
    exp_command_t ack = {0};
    ack.op = EXP_OP_ACK;
    ack.seq = st->seq;
    if (m->have_seq && st->seq == m->last_seq) {
        m->repeats++; /* our ACK was lost: acknowledge it again, report nothing */
        write_cmd(e, m, m->addr, &ack);
        return;
    }
    m->have_seq = true;
    m->last_seq = st->seq;
    bool armed = (m->armed_want & m->inputs & (1u << st->channel)) != 0;
    if (armed) {
        m->events++;
        exp_event_t ev = {0};
        ev.type = EXP_EVT_INPUT;
        ev.address = m->addr;
        ev.channel = st->channel;
        ev.kind = st->kind;
        ev.value = st->value;
        ev.t_ms = e->now - (e->now >= st->age_ms ? st->age_ms : e->now);
        ev.cap = m->cap[st->channel];
        emit(e, &ev);
    } else {
        m->dropped++;
    }
    write_cmd(e, m, m->addr, &ack);
}

static void poll(expansion_t *e, exp_module_t *m)
{
    m->next_poll = e->now + poll_period(m);
    for (int r = 0; r < EXP_READS_PER_POLL; r++) {
        const uint8_t ptr = EXP_REG_STATUS;
        uint8_t f[EXP_STATUS_LEN];
        m->polls++;
        if (read_reg(e, m->addr, &ptr, 1, f, sizeof(f)) != EXP_BUS_OK) {
            failed_read(e, m);
            return;
        }
        exp_status_t st;
        const char *why = expansion_parse_status(f, sizeof(f), m->ident.channels, &st);
        if (why != NULL) {
            m->refused_status++;
            failed_read(e, m);
            return; /* read again at the next poll */
        }
        m->fails = 0;
        if (st.flags & EXP_ST_FRESH) {
            if (!restarted(e, m)) return;
            st.flags &= (uint8_t)~EXP_ST_FRESH;
        }
        note_flags(e, m, st.flags);
        if (st.event) take_event(e, m, &st);
        if (r == 0) {
            if ((st.armed & m->inputs) != m->armed_want) {
                exp_command_t arm = {0};
                arm.op = EXP_OP_ARM;
                arm.armed = m->armed_want;
                write_cmd(e, m, m->addr, &arm);
            }
            reconcile_outputs(e, m, st.outputs);
        }
        if (!(st.event && (st.flags & EXP_ST_MORE))) return;
    }
}

void expansion_tick(expansion_t *e, uint32_t now_ms)
{
    e->now = now_ms;
    if (!e->started) return;
    probe_one(e);
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        exp_module_t *m = &e->mod[i];
        if (!m->used) continue;
        send_pending(e, m);
        if (due(now_ms, m->next_poll)) poll(e, m);
        if (m->used) refresh_lease(e, m);
    }
}
