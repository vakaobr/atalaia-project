/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's expansion port (see pod_port.h).
 */
#include "pod_port.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "pod_json.h"

static void say(const pod_port_t *pp, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(const pod_port_t *pp, const char *fmt, ...)
{
    if (pp->ops.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    pp->ops.log(pp->ops.ctx, line);
}

static bool emit(pod_port_t *pp, const char *cap, const char *event, const char *data)
{
    return pp->ops.emit != NULL && pp->ops.emit(pp->ops.ctx, cap, event, data);
}

/* ---- What the driver tells (expansion_box.h's ops) -------------------------------------- */

/* A hit of a channel the phone armed, while a phone is on a link: "hit.hit" with
 * {"strength"[,"channel"]}, sent as the EVT of capability "hit" (or "hit.<channel>"). */
static void xb_input(void *ctx, const char *type, const char *data_json)
{
    pod_port_t *pp = (pod_port_t *)ctx;
    if (strcmp(type, "hit.hit") != 0) return;
    double channel = 1;
    char cap[16] = "hit";
    if (pod_json_number(data_json, "channel", &channel) && channel >= 2 && channel <= XB_HITS_MAX) {
        snprintf(cap, sizeof(cap), "hit.%d", (int)channel);
    }
    if (emit(pp, cap, "hit", data_json)) pp->hits++;
}

/* node.module_lost: a module that went while a phone was on a link. */
static void xb_event(void *ctx, const char *type, const char *data_json)
{
    pod_port_t *pp = (pod_port_t *)ctx;
    if (strcmp(type, "node.module_lost") != 0) return;
    if (emit(pp, "pod", "module_lost", data_json)) pp->module_lost++;
}

static void xb_log(void *ctx, const char *line)
{
    const pod_port_t *pp = (const pod_port_t *)ctx;
    if (pp->ops.log != NULL) pp->ops.log(pp->ops.ctx, line);
}

/* ---- Setup ---------------------------------------------------------------------------- */

void pod_port_init(pod_port_t *pp, const exp_bus_t *bus, pod_outputs_t *po,
                   const pod_port_config_t *cfg, const pod_port_ops_t *ops)
{
    memset(pp, 0, sizeof(*pp));
    pp->po = po;
    if (cfg != NULL) pp->cfg = *cfg;
    if (pp->cfg.module_max_on_s < 1) pp->cfg.module_max_on_s = OUT_MAX_ON_DEFAULT_S;
    if (pp->cfg.module_max_on_s > OUT_MAX_ON_MAX_S) pp->cfg.module_max_on_s = OUT_MAX_ON_MAX_S;
    if (ops != NULL) pp->ops = *ops;
    if (bus == NULL) return;
    xb_ops_t xops = {.ctx = pp, .input = xb_input, .event = xb_event, .log = xb_log};
    expansion_box_init(&pp->xb, bus, po != NULL ? &po->out : NULL, &xops);
    pp->on = true;
}

void pod_port_start(pod_port_t *pp, uint32_t now_ms)
{
    if (pp->on) expansion_box_start(&pp->xb, now_ms);
}

/* A module's output channels join the output layer disabled (a box's admin enables them, EXP-28).
 * A pod built to lend them enables them as they come, at the build's longest on (the module's
 * when lower): building it in is the person at the pod saying so (EXPI9-5, EXPI9-18). */
static void enable_module_outputs(pod_port_t *pp)
{
    if (pp->po == NULL || !pp->cfg.module_outputs) return;
    outputs_t *o = &pp->po->out;
    for (int i = o->simple; i < o->count; i++) {
        out_channel_t *c = &o->ch[i];
        if (!c->module || c->set.enabled) continue;
        c->set.enabled = true;
        c->set.max_on_s =
            pp->cfg.module_max_on_s < c->module_max_s ? pp->cfg.module_max_on_s : c->module_max_s;
        if (pp->trimmed) {
            /* The last IDENT had no room for every output: one found since comes after them, so
             * it waits for the next IDENT to say whether it is lent (EXPI9-27). */
            c->withheld = true;
            say(pp, "module %02x channel %u enabled as %s, at most %lu s; lent once IDENT has room",
                c->addr, (unsigned)c->mch + 1u, c->id, (unsigned long)c->set.max_on_s);
            continue;
        }
        say(pp, "module %02x channel %u lent to the phone as %s, at most %lu s", c->addr,
            (unsigned)c->mch + 1u, c->id, (unsigned long)c->set.max_on_s);
    }
}

/* ---- What IDENT lends ------------------------------------------------------------------ */

/* The port's hit channels' descriptors, appended to the array json (len bytes, "[...]"). */
static size_t append_hits(const pod_port_t *pp, char *json, size_t len, size_t cap, bool channel)
{
    if (!pp->on || len < 2 || json[len - 1] != ']') return len;
    const expansion_t *e = &pp->xb.exp;
    int count = 0;
    for (int i = 0; i < EXP_MODULES_MAX; i++) {
        if (!e->mod[i].used) continue;
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) count += (e->mod[i].inputs >> c) & 1u;
    }
    if (count == 0) return len;
    char tail[ATALAIA_PROXY_JSON_MAX];
    size_t n = 0;
    bool first = len == 2;
    /* In address order, as node.modules lists them. */
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        const exp_module_t *m = expansion_module(e, (uint8_t)a);
        if (m == NULL) continue;
        for (int c = 0; c < EXP_CHANNELS_MAX; c++) {
            if (!((m->inputs >> c) & 1u)) continue;
            int num = expansion_box_hit_number(m->cap[c]);
            if (num == 0) continue;
            int w;
            if (channel && count > 1) {
                w = snprintf(tail + n, sizeof(tail) - n,
                             "%s{\"id\":\"%s\",\"type\":\"hit\",\"channel\":%d}", first ? "" : ",",
                             m->cap[c], num);
            } else {
                w = snprintf(tail + n, sizeof(tail) - n, "%s{\"id\":\"%s\",\"type\":\"hit\"}",
                             first ? "" : ",", m->cap[c]);
            }
            if (w < 0 || n + (size_t)w >= sizeof(tail)) return 0;
            n += (size_t)w;
            first = false;
        }
    }
    if (len - 1 + n + 2 > cap) return 0;
    memcpy(json + len - 1, tail, n);
    json[len - 1 + n] = ']';
    json[len + n] = '\0';
    return len + n;
}

int pod_port_ident_caps(pod_port_t *pp, const pod_caps_t *caps, pod_ident_level_t level, int trim,
                        char *out, size_t cap)
{
    pp->tell = true; /* the modules EVT follows every IDENT */
    pp->listing = 0;
    size_t n = caps != NULL ? pod_caps_descriptors(caps, out, cap, level == POD_IDENT_FULL) : 0;
    if (n == 0) {
        if (cap < 3) return 0;
        snprintf(out, cap, "[]");
        n = 2;
    }
    if (level < POD_IDENT_NO_PORT) {
        /* The 256 bytes are the encoder's to check (pod_send_ident then tries the next level);
         * the JSON buffer itself (ATALAIA_PROXY_JSON_MAX) holds far more. */
        size_t with = append_hits(pp, out, n, cap, level == POD_IDENT_FULL);
        if (with > 0) n = with;
    }
    if (level < POD_IDENT_NO_PORT && pp->po != NULL) {
        int all = outputs_enabled_count(&pp->po->out);
        int skip = level == POD_IDENT_TRIM && trim > 0 ? trim : 0;
        if (skip > all) skip = all;
        if (skip < all &&
            pod_outputs_append(pp->po, out, n, cap, level == POD_IDENT_FULL, skip) > 0) {
            pp->listing = all - skip;
        }
    }
    return pp->listing;
}

void pod_port_ident_sent(pod_port_t *pp, pod_ident_level_t level)
{
    if (pp->po == NULL) return;
    outputs_t *o = &pp->po->out;
    int lend = level < POD_IDENT_LEVELS ? pp->listing : 0;
    char left[POD_PORT_TEXT_MAX + 1] = "";
    size_t ll = 0;
    int k = 0, out_count = 0;
    bool back = false;
    /* The enabled outputs in IDENT's order: the first `lend` were listed (pod_outputs_append). */
    for (int i = 0; i < o->count; i++) {
        out_channel_t *c = &o->ch[i];
        if (!c->set.enabled) continue;
        bool withhold = k++ >= lend;
        if (!withhold) {
            back = back || c->withheld;
            c->withheld = false;
            continue;
        }
        /* Not in the IDENT the phone has: off now, and never switched until one lists it. */
        if (!c->withheld && c->on) {
            outputs_switch(o, c->id, OUT_ACT_OFF, 0, 0, 0, OUT_SRC_FIELD);
            say(pp, "output %s was on: off, left out of IDENT", c->id);
        }
        c->withheld = true;
        out_count++;
        int w = snprintf(left + ll, sizeof(left) - ll, "%s%s", ll ? ", " : "", c->id);
        if (w > 0 && ll + (size_t)w < sizeof(left)) ll += (size_t)w;
    }
    pp->trimmed = out_count > 0;
    if (out_count > 0) {
        say(pp, "IDENT has no room for %d output(s), not lent (off, refused): %s", out_count, left);
    } else if (back) {
        say(pp, "IDENT lends every output again");
    }
}

/* ---- What the field learns -------------------------------------------------------------- */

/* A module's output channel that the last IDENT left out (pod_port_ident_sent). */
static bool withheld(const pod_port_t *pp, uint8_t addr, int ch)
{
    if (pp->po == NULL) return false;
    const outputs_t *o = &pp->po->out;
    for (int i = o->simple; i < o->count; i++) {
        const out_channel_t *c = &o->ch[i];
        if (c->module && c->addr == addr && c->mch == ch) return c->withheld;
    }
    return false;
}

/* The modules' entries, as expansion_modules_text writes them, without the withheld channels (a
 * module left with none is left out). */
static size_t modules_text(const pod_port_t *pp, char *out, size_t cap)
{
    out[0] = '\0';
    size_t len = 0;
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) {
        const exp_module_t *m = expansion_module(&pp->xb.exp, (uint8_t)a);
        if (m == NULL) continue;
        char entry[EXP_MODULES_TEXT_MAX + 1];
        size_t n = expansion_module_text(m, entry, sizeof(entry));
        if (n == 0) continue;
        if (pp->trimmed) {
            char model[8];
            expansion_model_name(m->ident.model, model, sizeof(model));
            int w = snprintf(entry, sizeof(entry), "%02x:%s/%u.%u.%u:", m->addr, model,
                             m->ident.fw[0], m->ident.fw[1], m->ident.fw[2]);
            n = w > 0 ? (size_t)w : 0;
            bool any = false;
            for (int c = 0; c < m->ident.channels && n > 0 && n < sizeof(entry); c++) {
                if (!(m->usable & (1u << c)) || withheld(pp, m->addr, c)) continue;
                w = snprintf(entry + n, sizeof(entry) - n, "%s%s", any ? "," : "", m->cap[c]);
                n = w > 0 ? n + (size_t)w : 0;
                any = true;
            }
            if (!any || n == 0 || n >= sizeof(entry)) continue;
        }
        size_t need = n + (len > 0 ? 1 : 0);
        if (len + need > EXP_MODULES_TEXT_MAX || len + need + 1 > cap) continue; /* whole only */
        if (len > 0) out[len++] = ';';
        memcpy(out + len, entry, n + 1);
        len += n;
    }
    return len;
}

/* Appends src's entries ("a;b;c") to out (len bytes so far) one by one, whole entries only, while
 * out stays within limit bytes: the modules' after the simple outputs' (as box_game.c). */
static size_t append_entries(char *out, size_t len, size_t limit, const char *src)
{
    for (const char *entry = src; *entry;) {
        const char *semi = strchr(entry, ';');
        size_t el = semi != NULL ? (size_t)(semi - entry) : strlen(entry);
        size_t need = el + (len > 0 ? 1 : 0);
        if (len + need > limit) break;
        if (len > 0) out[len++] = ';';
        memcpy(out + len, entry, el);
        len += el;
        out[len] = '\0';
        if (semi == NULL) break;
        entry = semi + 1;
    }
    return len;
}

size_t pod_port_modules_text(const pod_port_t *pp, char *out, size_t cap)
{
    if (cap == 0) return 0;
    out[0] = '\0';
    size_t limit = cap - 1 < POD_PORT_TEXT_MAX ? cap - 1 : POD_PORT_TEXT_MAX;
    size_t len = pp->po != NULL ? outputs_modules_text(&pp->po->out, out, limit + 1) : 0;
    if (!pp->on) return len;
    char mods[EXP_MODULES_TEXT_MAX + 1];
    if (modules_text(pp, mods, sizeof(mods)) == 0) return len;
    return append_entries(out, len, limit, mods);
}

size_t pod_port_withheld_text(const pod_port_t *pp, char *out, size_t cap)
{
    if (cap == 0) return 0;
    out[0] = '\0';
    if (pp->po == NULL) return 0;
    size_t limit = cap - 1 < POD_PORT_TEXT_MAX ? cap - 1 : POD_PORT_TEXT_MAX;
    /* The box's own node.outputs_disabled builders: a withheld channel counts as not enabled. */
    size_t len = outputs_disabled_text(&pp->po->out, out, limit + 1);
    if (!pp->on) return len;
    char mods[EXP_MODULES_TEXT_MAX + 1];
    if (expansion_box_disabled_text(&pp->xb, mods, sizeof(mods)) == 0) return len;
    return append_entries(out, len, limit, mods);
}

size_t pod_port_max_on_json(const pod_port_t *pp, char *out, size_t cap)
{
    if (cap < 3) return 0;
    size_t len = (size_t)snprintf(out, cap, "{");
    if (pp->po != NULL) {
        const outputs_t *o = &pp->po->out;
        for (int i = 0; i < o->count; i++) {
            const out_channel_t *c = &o->ch[i];
            if (!c->set.enabled || c->withheld) continue;
            int w = snprintf(out + len, cap - len, "%s\"%s\":%lu", len > 1 ? "," : "", c->id,
                             (unsigned long)c->set.max_on_s);
            if (w < 0 || len + (size_t)w + 2 > cap) return 0;
            len += (size_t)w;
        }
    }
    out[len++] = '}';
    out[len] = '\0';
    return len;
}

size_t pod_port_status_json(const pod_port_t *pp, char *out, size_t cap)
{
    if (pp->on) return expansion_box_status_json(&pp->xb, out, cap);
    if (cap < 3) return 0;
    return (size_t)snprintf(out, cap, "[]");
}

/* What was told (or found with nothing to tell), so that only a change is told again. */
static void keep_told(pod_port_t *pp, const char *text, const char *max_on, bool has_withheld,
                      const char *withheld)
{
    pp->told = true;
    snprintf(pp->told_text, sizeof(pp->told_text), "%s", text);
    snprintf(pp->told_max, sizeof(pp->told_max), "%s", max_on);
    pp->told_has_withheld = has_withheld;
    snprintf(pp->told_withheld, sizeof(pp->told_withheld), "%s", withheld);
}

/* The modules EVT: after an IDENT, and when what it says changes while a phone is on a link. */
static void tell_modules(pod_port_t *pp)
{
    char text[POD_PORT_TEXT_MAX + 1], max_on[sizeof(pp->told_max)];
    char withheld[POD_PORT_TEXT_MAX + 1];
    pod_port_modules_text(pp, text, sizeof(text));
    if (pod_port_max_on_json(pp, max_on, sizeof(max_on)) == 0)
        snprintf(max_on, sizeof(max_on), "{}");
    pod_port_withheld_text(pp, withheld, sizeof(withheld));
    /* "withheld" (decision PROPC-6) only from a pod with an output fitted, as a box sends
     * node.outputs_disabled (EXPL-15), and once more, empty, from one that lost its last output
     * after telling some (EXPL-21). */
    bool fitted = pp->po != NULL && pp->po->out.count > 0;
    bool has_withheld = fitted || pp->told_withheld[0] != '\0';
    bool lent_changed = strcmp(text, pp->told_text) != 0 || strcmp(max_on, pp->told_max) != 0;
    bool changed = lent_changed || has_withheld != pp->told_has_withheld ||
                   strcmp(withheld, pp->told_withheld) != 0;
    if (pp->told && !pp->tell && !changed) return;
    if (text[0] == '\0' && withheld[0] == '\0' && !pp->said) {
        /* Nothing to tell and nothing told before: a pod without outputs or modules says nothing
         * new, as a box (box_game.c). */
        pp->tell = false;
        keep_told(pp, text, max_on, has_withheld, withheld);
        return;
    }
    if (pp->told && lent_changed && !pp->tell && pp->ops.ident_changed != NULL) {
        /* What IDENT lends changed too (a module found or lost, a channel renamed): IDENT first.
         * The withheld outputs alone are no part of IDENT. */
        pp->ops.ident_changed(pp->ops.ctx);
    }
    pp->tell = false;
    char tail[POD_PORT_TEXT_MAX + 16] = "";
    if (has_withheld) snprintf(tail, sizeof(tail), ",\"withheld\":\"%s\"", withheld);
    char data[2 * POD_PORT_TEXT_MAX + sizeof(max_on) + 48];
    snprintf(data, sizeof(data), "{\"modules\":\"%s\",\"max_on_s\":%s%s}", text, max_on, tail);
    bool sent = emit(pp, "pod", "modules", data);
    if (!sent && has_withheld) {
        /* Too big for one EVT (a pod with many outputs): the two texts (at most 100 bytes each
         * always fit); the phone keeps its 30 s. */
        snprintf(data, sizeof(data), "{\"modules\":\"%s\"%s}", text, tail);
        sent = emit(pp, "pod", "modules", data);
    }
    if (!sent) {
        /* The text alone. */
        snprintf(data, sizeof(data), "{\"modules\":\"%s\"}", text);
        sent = emit(pp, "pod", "modules", data);
    }
    if (!sent) {
        pp->tell = true; /* tried again at the next tick (IDENT is not sent again for it) */
        return;
    }
    pp->said = pp->said || text[0] != '\0' || withheld[0] != '\0';
    keep_told(pp, text, max_on, has_withheld, withheld);
    say(pp, "told the phone its modules: %s", text[0] ? text : "(none)");
    if (withheld[0] != '\0') say(pp, "told the phone its outputs not lent: %s", withheld);
}

void pod_port_tick(pod_port_t *pp, bool phone_on, uint32_t now_ms)
{
    if (!phone_on) {
        pp->told = false; /* told again once a phone links */
        pp->tell = false;
    }
    pp->phone = phone_on;
    if (pp->on) {
        /* A phone on a link stands for a running game: hits it armed reach it, the others are
         * disarmed; when the last link goes the arming is forgotten (expansion_box_tick). */
        expansion_box_tick(&pp->xb, phone_on ? OUT_GAME_RUNNING : OUT_GAME_NONE, now_ms);
        enable_module_outputs(pp);
    }
    if (phone_on && (pp->told || pp->tell)) tell_modules(pp);
}

/* ---- Commands -------------------------------------------------------------------------- */

bool pod_port_owns(const pod_port_t *pp, const char *cap_id)
{
    return pp->on && expansion_box_hit_number(cap_id) > 0;
}

bool pod_port_command(pod_port_t *pp, const atalaia_proxy_msg_t *m)
{
    if (strcmp(m->name, "arm") != 0 && strcmp(m->name, "disarm") != 0) return false;
    expansion_box_command(&pp->xb, m->cap_id, m->name);
    return true;
}
