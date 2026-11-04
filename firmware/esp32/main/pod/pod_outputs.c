/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's simple outputs (see pod_outputs.h).
 */
#include "pod_outputs.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "pod_json.h"

static void say(const pod_outputs_t *po, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void say(const pod_outputs_t *po, const char *fmt, ...)
{
    if (po->out.ops.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    po->out.ops.log(po->out.ops.ctx, line);
}

void pod_outputs_init(pod_outputs_t *po, const outputs_ops_t *ops)
{
    memset(po, 0, sizeof(*po));
    outputs_ops_t o;
    memset(&o, 0, sizeof(o));
    if (ops != NULL) o = *ops;
    /* The phone tells the field what it switched (output.switched); the pod keeps no settings
     * of its own to store. */
    o.event = NULL;
    o.save = NULL;
    outputs_init(&po->out, &o);
}

bool pod_outputs_owns(const pod_outputs_t *po, const char *cap_id)
{
    int i = outputs_find(&po->out, cap_id);
    return i >= 0 && po->out.ch[i].set.enabled && !po->out.ch[i].withheld;
}

size_t pod_outputs_append(const pod_outputs_t *po, char *json, size_t len, size_t cap,
                          bool feedback, int trim)
{
    if (len < 2 || json[0] != '[' || json[len - 1] != ']') return 0;
    char tail[ATALAIA_PROXY_JSON_MAX];
    size_t n = 0;
    bool first = len == 2; /* "[]": no comma before the first */
    int lend = outputs_enabled_count(&po->out) - (trim > 0 ? trim : 0);
    /* The simple outputs first, then a module's output channels (the expansion port: pod_port.h);
     * only a simple output says "feedback": false (a module's channel leaves the key out). */
    for (int i = 0; i < po->out.count && lend > 0; i++) {
        const out_channel_t *c = &po->out.ch[i];
        if (!c->set.enabled) continue;
        lend--;
        bool flag = feedback && !c->module;
        int w = snprintf(tail + n, sizeof(tail) - n, "%s{\"id\":\"%s\",\"type\":\"output\"%s}",
                         first ? "" : ",", c->id, flag ? ",\"feedback\":false" : "");
        if (w < 0 || n + (size_t)w >= sizeof(tail)) return 0;
        n += (size_t)w;
        first = false;
    }
    if (len - 1 + n + 2 > cap) return 0; /* the array without its ']', the tail, "]" and NUL */
    memcpy(json + len - 1, tail, n);
    json[len - 1 + n] = ']';
    json[len + n] = '\0';
    return len + n;
}

/* A whole number argument: 1 when it is there and whole (in *v), 0 when absent, -1 otherwise. */
static int whole_arg(const char *json, const char *key, double *v)
{
    if (!pod_json_has(json, key)) return 0;
    return pod_json_number(json, key, v) && floor(*v) == *v ? 1 : -1;
}

static bool refuse(pod_outputs_t *po, const atalaia_proxy_msg_t *m, const char *why)
{
    po->refused++;
    say(po, "CMD %s.%s refused: %s", m->cap_id, m->name, why);
    return true;
}

bool pod_outputs_command(pod_outputs_t *po, const atalaia_proxy_msg_t *m)
{
    out_act_t act;
    if (strcmp(m->name, "on") == 0) {
        act = OUT_ACT_ON;
    } else if (strcmp(m->name, "off") == 0) {
        act = OUT_ACT_OFF;
    } else if (strcmp(m->name, "pulse") == 0) {
        act = OUT_ACT_PULSE;
    } else if (strcmp(m->name, "pattern") == 0) {
        act = OUT_ACT_PATTERN;
    } else {
        return false;
    }
    double ms = 0, on_ms = 0, off_ms = 0;
    if (act != OUT_ACT_OFF) {
        /* As CMD 12 (protocol/vectors/cmd.json): ms is required, 1 to 600000; a pattern's times
         * 10 to 10000 (the output layer raises their floor to 500 ms). */
        int has = whole_arg(m->data_json, "ms", &ms);
        if (has == 0) return refuse(po, m, "ms is required for on, pulse and pattern");
        if (has < 0 || ms < 1 || ms > OUT_MS_MAX) return refuse(po, m, "ms is 1 to 600000");
        if (act == OUT_ACT_PATTERN) {
            int a = whole_arg(m->data_json, "on_ms", &on_ms);
            int b = whole_arg(m->data_json, "off_ms", &off_ms);
            if (a <= 0 || b <= 0 || on_ms < OUT_PATTERN_MIN_MS || on_ms > OUT_PATTERN_MAX_MS ||
                off_ms < OUT_PATTERN_MIN_MS || off_ms > OUT_PATTERN_MAX_MS) {
                return refuse(po, m, "on_ms and off_ms are 10 to 10000");
            }
        }
    }
    /* The CMD came on a link, so a phone is on one now, even before the loop's next tick has
     * seen it (a phone that links again and switches at once). */
    if (!po->linked) {
        po->linked = true;
        outputs_game_start(&po->out);
    }
    /* The field's source: the phone forwards its mode's calls and the controller's CMD 12 alike,
     * and keeps a script's rate limit itself. */
    out_result_t r = outputs_switch(&po->out, m->cap_id, act, (uint32_t)ms, (uint32_t)on_ms,
                                    (uint32_t)off_ms, OUT_SRC_FIELD);
    if (r != OUT_OK) return refuse(po, m, outputs_result_name(r));
    po->commands++;
    return true;
}

bool pod_outputs_any_on(const pod_outputs_t *po)
{
    for (int i = 0; i < po->out.count; i++) {
        if (po->out.ch[i].on) return true;
    }
    return false;
}

void pod_outputs_tick(pod_outputs_t *po, bool phone_on, uint32_t heard_ms, uint32_t now_ms)
{
    bool on = pod_outputs_any_on(po);
    bool quiet = phone_on && on && (uint32_t)(now_ms - heard_ms) >= POD_OUT_QUIET_MS;
    if (quiet) {
        po->quiet_offs++;
        say(po, "the phone said nothing for %u ms with an output on: every output off",
            (unsigned)POD_OUT_QUIET_MS);
    } else if (!phone_on && po->linked && on) {
        po->link_offs++;
        say(po, "the phone's link went: every output off");
    }
    po->linked = phone_on && !quiet;
    /* No phone (or a silent one): the output layer's "no game", which turns every output off and
     * ends the signal (1.0 ms pulses for 0.5 s, then the pin low). A phone on a link: a running
     * game, as the output layer sees it (the phone keeps the game's own rules). */
    outputs_tick(&po->out, po->linked ? OUT_GAME_RUNNING : OUT_GAME_NONE, now_ms);
}
