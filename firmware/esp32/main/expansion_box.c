/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port in the box's game (expansion_box.h; draft RFC "The expansion port",
 * increment 8).
 */
#include "expansion_box.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static const char *const HINT_FUNCTION[EXP_HINT_COUNT] = {NULL,    "siren", "strobe",
                                                          "smoke", "light", "horn"};

static void say(const expansion_box_t *xb, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void say(const expansion_box_t *xb, const char *fmt, ...)
{
    if (xb->ops.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    xb->ops.log(xb->ops.ctx, line);
}

int expansion_box_hit_number(const char *cap)
{
    if (cap == NULL || strncmp(cap, "hit", 3) != 0) return 0;
    if (cap[3] == '\0') return 1;
    if (cap[3] == '.' && cap[4] >= '2' && cap[4] <= '0' + XB_HITS_MAX && cap[5] == '\0') {
        return cap[4] - '0';
    }
    return 0;
}

static int slot_of(const expansion_box_t *xb, const exp_module_t *m)
{
    return (int)(m - xb->exp.mod);
}

static bool game_on(out_game_t g)
{
    return g == OUT_GAME_RUNNING || g == OUT_GAME_PAUSED;
}

/* How many hit channels the box has now (a second one adds "channel" to each hit). */
static int hit_channels(const expansion_box_t *xb)
{
    int n = 0;
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        const exp_module_t *m = &xb->exp.mod[i];
        if (!m->used) continue;
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) n += (m->inputs >> c) & 1u;
    }
    return n;
}

bool expansion_box_has_hit(const expansion_box_t *xb)
{
    return hit_channels(xb) > 0;
}

/* ---- The output layer's names ------------------------------------------------------------ */

/* The output layer names every output (a simple output first): the driver's entries follow. */
static void sync_names(expansion_box_t *xb)
{
    if (xb->outs == NULL) return;
    for (int i = xb->outs->simple; i < xb->outs->count; i++) {
        const out_channel_t *c = &xb->outs->ch[i];
        const exp_module_t *m = expansion_module(&xb->exp, c->addr);
        if (m == NULL || c->mch >= EXP_CHANNELS_MAX) continue;
        if (strcmp(m->cap[c->mch], c->id) != 0 &&
            expansion_set_cap(&xb->exp, c->addr, c->mch, c->id)) {
            xb->changes++;
        }
    }
}

static void add_outputs(expansion_box_t *xb, const exp_module_t *m)
{
    if (xb->outs == NULL || m->outputs == 0) return;
    int slot = slot_of(xb, m);
    for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
        if (!(m->outputs & (1u << c))) continue;
        exp_out_ref_t *r = &xb->refs[slot][c];
        r->exp = &xb->exp;
        r->addr = m->addr;
        r->channel = (uint8_t)c;
        char fn[OUT_ID_MAX + 1];
        uint8_t hint = m->ch[c].hint < EXP_HINT_COUNT ? m->ch[c].hint : 0;
        if (HINT_FUNCTION[hint] != NULL) {
            snprintf(fn, sizeof(fn), "%s", HINT_FUNCTION[hint]);
        } else {
            snprintf(fn, sizeof(fn), "out.%d", c + 1);
        }
        out_backend_t be = {.ctx = r, .drive = NULL, .set = expansion_box_backend_set};
        if (outputs_add_module(xb->outs, m->addr, (uint8_t)c, fn,
                               (m->ch[c].flags & EXP_CH_RELAY) != 0, m->ch[c].max_on_s, &be) < 0) {
            say(xb, "expansion: 0x%02X channel %d not used: the box takes %d module outputs",
                m->addr, c + 1, OUT_MODULE_CHANNELS);
        }
    }
    sync_names(xb);
}

/* ---- What the driver tells ---------------------------------------------------------------- */

static void on_event(void *ctx, const exp_event_t *e)
{
    expansion_box_t *xb = (expansion_box_t *)ctx;
    switch (e->type) {
    case EXP_EVT_ADDED: {
        const exp_module_t *m = expansion_module(&xb->exp, e->address);
        if (m != NULL) add_outputs(xb, m);
        xb->changes++;
        break;
    }
    case EXP_EVT_LOST: {
        if (xb->outs != NULL) outputs_remove_module(xb->outs, e->address);
        xb->lost++;
        xb->changes++;
        if (game_on(xb->game) && xb->ops.event != NULL) {
            char data[EXP_MODULES_TEXT_MAX + 48];
            snprintf(data, sizeof(data), "{\"modules\":\"%s\",\"reason\":\"%s\"}",
                     e->text != NULL ? e->text : "", e->reason != NULL ? e->reason : "no_answer");
            xb->ops.event(xb->ops.ctx, "node.module_lost", data);
        }
        break;
    }
    case EXP_EVT_INPUT: {
        int n = expansion_box_hit_number(e->cap);
        if (e->kind != EXP_EV_HIT || n == 0 || xb->game != OUT_GAME_RUNNING ||
            xb->ops.input == NULL) {
            xb->dropped++;
            break;
        }
        char data[48];
        if (hit_channels(xb) > 1) {
            snprintf(data, sizeof(data), "{\"strength\":%u,\"channel\":%d}", (unsigned)e->value, n);
        } else {
            snprintf(data, sizeof(data), "{\"strength\":%u}", (unsigned)e->value);
        }
        xb->hits++;
        say(xb, "expansion: %s hit, strength %u", e->cap, (unsigned)e->value);
        xb->ops.input(xb->ops.ctx, "hit.hit", data);
        break;
    }
    case EXP_EVT_OVERFLOW:
        say(xb, "expansion: 0x%02X dropped events (its queue was full)", e->address);
        break;
    }
}

static void on_log(void *ctx, const char *line)
{
    const expansion_box_t *xb = (const expansion_box_t *)ctx;
    if (xb->ops.log != NULL) xb->ops.log(xb->ops.ctx, line);
}

/* ---- The game task ------------------------------------------------------------------------ */

void expansion_box_init(expansion_box_t *xb, const exp_bus_t *bus, outputs_t *outs,
                        const xb_ops_t *ops)
{
    memset(xb, 0, sizeof(*xb));
    if (ops != NULL) xb->ops = *ops;
    xb->outs = outs;
    xb->game = OUT_GAME_NONE;
    exp_ops_t eops = {.ctx = xb, .event = on_event, .log = on_log};
    expansion_init(&xb->exp, bus, &eops);
}

void expansion_box_start(expansion_box_t *xb, uint32_t now_ms)
{
    expansion_start(&xb->exp, now_ms);
}

/* The hit channels the script armed, while a game runs; none otherwise (EXP-10: a disarmed
 * channel's events are dropped on the module). */
static void apply_arming(expansion_box_t *xb)
{
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        exp_module_t *m = &xb->exp.mod[i];
        if (!m->used || m->inputs == 0) continue;
        uint8_t want = 0;
        if (xb->game == OUT_GAME_RUNNING) {
            for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
                if (!(m->inputs & (1u << c))) continue;
                int n = expansion_box_hit_number(m->cap[c]);
                if (n > 0 && (xb->armed & (1u << (n - 1)))) want = (uint8_t)(want | (1u << c));
            }
        }
        if (want != m->armed_want) expansion_arm(&xb->exp, m->addr, want);
    }
}

void expansion_box_tick(expansion_box_t *xb, out_game_t game, uint32_t now_ms)
{
    if (game_on(xb->game) && !game_on(game)) xb->armed = 0; /* the game is over */
    xb->game = game;
    apply_arming(xb);
    expansion_tick(&xb->exp, now_ms);
    sync_names(xb);
}

bool expansion_box_command(expansion_box_t *xb, const char *target, const char *method)
{
    int n = expansion_box_hit_number(target);
    if (n == 0 || method == NULL) return false;
    uint8_t bit = (uint8_t)(1u << (n - 1));
    if (strcmp(method, "arm") == 0) {
        xb->armed = (uint8_t)(xb->armed | bit);
    } else if (strcmp(method, "disarm") == 0) {
        xb->armed = (uint8_t)(xb->armed & ~bit);
    } else {
        return true; /* a hit capability's unknown method: nothing to do */
    }
    apply_arming(xb);
    return true;
}

size_t expansion_box_modules_text(const expansion_box_t *xb, char *out, size_t cap)
{
    return expansion_modules_text(&xb->exp, out, cap);
}

size_t expansion_box_disabled_text(const expansion_box_t *xb, char *out, size_t cap)
{
    if (cap == 0) return 0;
    out[0] = '\0';
    if (xb->outs == NULL) return 0;
    const outputs_t *o = xb->outs;
    size_t len = 0;
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        const exp_module_t *m = expansion_module(&xb->exp, (uint8_t)a);
        if (m == NULL) continue;
        char model[8], entry[EXP_MODULES_TEXT_MAX + 1];
        expansion_model_name(m->ident.model, model, sizeof(model));
        int n = snprintf(entry, sizeof(entry), "%02x:%s/%u.%u.%u:", m->addr, model, m->ident.fw[0],
                         m->ident.fw[1], m->ident.fw[2]);
        bool any = false;
        for (int i = o->simple; i < o->count && n > 0 && (size_t)n < sizeof(entry); i++) {
            const out_channel_t *c = &o->ch[i];
            if (!c->module || c->addr != m->addr || (c->set.enabled && !c->withheld)) continue;
            n += snprintf(entry + n, sizeof(entry) - (size_t)n, "%s%s", any ? "," : "", c->id);
            any = true;
        }
        if (!any || n <= 0 || (size_t)n >= sizeof(entry)) continue; /* none, or too long whole */
        size_t need = (size_t)n + (len > 0 ? 1 : 0);
        if (len + need > EXP_MODULES_TEXT_MAX || len + need + 1 > cap) continue; /* whole only */
        if (len > 0) out[len++] = ';';
        memcpy(out + len, entry, (size_t)n + 1);
        len += (size_t)n;
    }
    return len;
}

size_t expansion_box_status_json(const expansion_box_t *xb, char *out, size_t cap)
{
    if (cap < 3) return 0;
    size_t len = (size_t)snprintf(out, cap, "[");
    bool first = true;
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST && len + 2 < cap; a++) {
        const exp_module_t *m = expansion_module(&xb->exp, (uint8_t)a);
        if (m == NULL) continue;
        char model[8], caps[EXP_MODULES_TEXT_MAX + 1] = "";
        expansion_model_name(m->ident.model, model, sizeof(model));
        size_t cl = 0;
        for (int c = 0; c < m->ident.channels && cl + 4 < sizeof(caps); c++) {
            if (!(m->usable & (1u << c))) continue;
            cl += (size_t)snprintf(caps + cl, sizeof(caps) - cl, "%s\"%s\"", cl ? "," : "",
                                   m->cap[c]);
        }
        int n = snprintf(out + len, cap - len,
                         "%s{\"address\":\"%02x\",\"model\":\"%s\",\"fw\":\"%u.%u.%u\","
                         "\"caps\":[%s],\"armed\":%u,\"events\":%lu,\"polls\":%lu}",
                         first ? "" : ",", m->addr, model, m->ident.fw[0], m->ident.fw[1],
                         m->ident.fw[2], caps, (unsigned)m->armed_want, (unsigned long)m->events,
                         (unsigned long)m->polls);
        if (n < 0 || len + (size_t)n + 2 > cap) break;
        len += (size_t)n;
        first = false;
    }
    len += (size_t)snprintf(out + len, cap - len, "]");
    return len;
}

/* ---- Behind the output layer ------------------------------------------------------------- */

out_result_t expansion_box_backend_set(void *ctx, const out_want_t *want, uint32_t now_ms)
{
    const exp_out_ref_t *r = (const exp_out_ref_t *)ctx;
    exp_desired_t d = {EXP_MODE_OFF, 0, 0, 0};
    if (want->on) {
        d.mode = want->pattern ? EXP_MODE_PATTERN : EXP_MODE_ON;
        d.until_ms = want->until_ms;
        d.on_ms = want->pattern ? want->on_ms : 0;
        d.off_ms = want->pattern ? want->off_ms : 0;
    }
    switch (expansion_output(r->exp, r->addr, r->channel, &d, now_ms)) {
    case EXP_OK: return OUT_OK;
    case EXP_NO_SUCH: return OUT_NO_SUCH;
    case EXP_BAD_ARGS: return OUT_BAD_ARGS;
    case EXP_TOO_SOON: return OUT_TOO_SOON;
    }
    return OUT_BAD_ARGS;
}
