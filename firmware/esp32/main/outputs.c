/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's output layer (outputs.h; draft RFC "The expansion port", increment 2).
 */
#include "outputs.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "screen_json.h"

/* a is at or after b, on a clock that wraps. */
static bool at_or_after(uint32_t a, uint32_t b)
{
    return (int32_t)(a - b) >= 0;
}

static void say(const outputs_t *o, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(const outputs_t *o, const char *fmt, ...)
{
    if (o->ops.log == NULL) return;
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    o->ops.log(o->ops.ctx, line);
}

static void tell(const outputs_t *o, const char *type, const char *data_json)
{
    if (o->ops.event != NULL) o->ops.event(o->ops.ctx, type, data_json);
}

const char *outputs_result_name(out_result_t r)
{
    switch (r) {
    case OUT_OK: return "ok";
    case OUT_NO_SUCH: return "no such output";
    case OUT_DISABLED: return "disabled at the box";
    case OUT_NOT_NOW: return "no game running";
    case OUT_BAD_ARGS: return "bad arguments";
    case OUT_TOO_SOON: return "too soon after its last change";
    case OUT_RATE: return "more than 2 starts a second";
    case OUT_BUSY: return "not during a game";
    }
    return "?";
}

const char *outputs_source_name(out_source_t s)
{
    switch (s) {
    case OUT_SRC_SCRIPT: return "script";
    case OUT_SRC_FIELD: return "field";
    case OUT_SRC_GM: return "gm";
    case OUT_SRC_BOX_ADMIN: return "box_admin";
    }
    return "?";
}

const char *outputs_game_name(out_game_t g)
{
    switch (g) {
    case OUT_GAME_NONE: return "none";
    case OUT_GAME_RUNNING: return "running";
    case OUT_GAME_PAUSED: return "paused";
    case OUT_GAME_ENDED: return "ended";
    case OUT_GAME_HALTED: return "halted";
    }
    return "?";
}

/* ---- Settings --------------------------------------------------------------------- */

static const char *const functions[] = {"siren", "strobe", "smoke", "light", "horn"};

bool outputs_id_ok(const char *id)
{
    if (id == NULL) return false;
    size_t n = strlen(id);
    if (n == 0 || n > OUT_ID_MAX) return false;
    for (size_t i = 0; i < n; i++) {
        char c = id[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '.' || c == '_' ||
              c == '-')) {
            return false;
        }
    }
    return true;
}

bool outputs_function_ok(const char *function)
{
    if (function == NULL) return false;
    for (size_t i = 0; i < sizeof(functions) / sizeof(functions[0]); i++) {
        if (strcmp(function, functions[i]) == 0) return true;
    }
    return strncmp(function, "out.", 4) == 0 && function[4] >= '1' && function[4] <= '9' &&
           function[5] == '\0';
}

void outputs_default_settings(int index, out_settings_t *s)
{
    memset(s, 0, sizeof(*s));
    s->enabled = false;
    snprintf(s->function, sizeof(s->function), "out.%d", index + 1);
    s->max_on_s = OUT_MAX_ON_DEFAULT_S;
}

static bool settings_ok(const out_settings_t *s)
{
    return s != NULL && outputs_function_ok(s->function) && s->max_on_s >= 1 &&
           s->max_on_s <= OUT_MAX_ON_MAX_S;
}

/* Capability ids from the functions: a second channel with the same function is "<fn>.2". The
 * functions are short (outputs_function_ok), so "<fn>.<n>" always fits. */
static void name_channels(outputs_t *o)
{
    for (int i = 0; i < o->count; i++) {
        int same = 0;
        for (int j = 0; j < i; j++) {
            if (strcmp(o->ch[j].set.function, o->ch[i].set.function) == 0) same++;
        }
        char id[OUT_ID_MAX + 16];
        if (same == 0) {
            snprintf(id, sizeof(id), "%s", o->ch[i].set.function);
        } else {
            snprintf(id, sizeof(id), "%s.%d", o->ch[i].set.function, same + 1);
        }
        size_t n = strlen(id);
        if (n > OUT_ID_MAX) n = OUT_ID_MAX;
        memcpy(o->ch[i].id, id, n);
        o->ch[i].id[n] = '\0';
    }
}

void outputs_init(outputs_t *o, const outputs_ops_t *ops)
{
    memset(o, 0, sizeof(*o));
    if (ops != NULL) o->ops = *ops;
    o->game = OUT_GAME_NONE;
}

int outputs_add_simple(outputs_t *o, int gpio, const out_backend_t *be, const out_settings_t *saved)
{
    if (o->count >= OUTPUTS_MAX) return -1;
    int i = o->count++;
    out_channel_t *c = &o->ch[i];
    memset(c, 0, sizeof(*c));
    c->gpio = gpio;
    if (be != NULL) c->be = *be;
    if (settings_ok(saved)) {
        c->set = *saved;
    } else {
        outputs_default_settings(i, &c->set);
    }
    name_channels(o);
    say(o, "output %d on GPIO %d: %s, %s, at most %lu s", i + 1, gpio, c->id,
        c->set.enabled ? "enabled" : "disabled (the admin enables it at the box)",
        (unsigned long)c->set.max_on_s);
    return i;
}

/* ---- State ------------------------------------------------------------------------ */

static bool level_now(const out_channel_t *c, uint32_t now)
{
    if (!c->on) return false;
    if (!c->pattern) return true;
    uint32_t period = c->on_ms + c->off_ms;
    return period == 0 || (now - c->start_ms) % period < c->on_ms;
}

/* What the channel shows: noted with the time it changed (the state-change floor). */
static void update_level(out_channel_t *c, uint32_t now)
{
    bool level = level_now(c, now);
    if (level != c->level) {
        c->level = level;
        c->changed = true;
        c->change_ms = now;
    }
}

/* Off now. tell: say so with output.switched (an off before its time, by src). */
static void turn_off(outputs_t *o, out_channel_t *c, out_source_t src, bool tell_it)
{
    if (!c->on) return;
    c->on = false;
    update_level(c, o->now);
    if (tell_it) {
        char data[96];
        snprintf(data, sizeof(data), "{\"capability\":\"%s\",\"ms\":0,\"source\":\"%s\"}", c->id,
                 outputs_source_name(src));
        tell(o, "output.switched", data);
        say(o, "output %s: off (%s)", c->id, outputs_source_name(src));
    }
}

/* The game state turns every output off: no output.switched (the state says why). */
static void all_off(outputs_t *o, const char *why)
{
    bool any = false;
    for (int i = 0; i < o->count; i++) {
        if (o->ch[i].on) any = true;
        turn_off(o, &o->ch[i], OUT_SRC_FIELD, false);
    }
    if (any) say(o, "every output off: %s", why);
}

out_result_t outputs_configure(outputs_t *o, int index, const out_settings_t *s)
{
    if (index < 0 || index >= o->count) return OUT_NO_SUCH;
    if (!settings_ok(s)) return OUT_BAD_ARGS;
    if (o->game == OUT_GAME_RUNNING || o->game == OUT_GAME_PAUSED || o->game == OUT_GAME_HALTED ||
        o->grace) {
        return OUT_BUSY;
    }
    out_channel_t *c = &o->ch[index];
    c->set = *s;
    if (!c->set.enabled) turn_off(o, c, OUT_SRC_BOX_ADMIN, false);
    name_channels(o);
    if (o->ops.save != NULL && !o->ops.save(o->ops.ctx, index, &c->set)) {
        say(o, "output %d: the settings could not be stored (kept until the box restarts)",
            index + 1);
    }
    say(o, "output %d on GPIO %d: %s, %s, at most %lu s (set at the box)", index + 1, c->gpio,
        c->id, c->set.enabled ? "enabled" : "disabled", (unsigned long)c->set.max_on_s);
    return OUT_OK;
}

void outputs_game_end(outputs_t *o, uint32_t now_ms)
{
    if (o->game != OUT_GAME_RUNNING && o->game != OUT_GAME_PAUSED) return;
    o->now = now_ms;
    all_off(o, "the game ended");
    o->game = OUT_GAME_ENDED;
    o->grace = true;
    o->grace_until = now_ms + OUT_GRACE_MS;
}

static void game_starts(outputs_t *o)
{
    all_off(o, "a game starts");
    o->grace = false;
    for (int i = 0; i < o->count; i++) {
        o->ch[i].rate_told = false;
        o->ch[i].start_count = 0;
    }
}

void outputs_game_start(outputs_t *o)
{
    if (o->game == OUT_GAME_RUNNING) return;
    game_starts(o);
    o->game = OUT_GAME_RUNNING;
}

void outputs_tick(outputs_t *o, out_game_t game, uint32_t now_ms)
{
    o->now = now_ms;
    if (game != o->game) {
        switch (game) {
        case OUT_GAME_RUNNING: game_starts(o); break;
        case OUT_GAME_ENDED:
            if (o->game == OUT_GAME_RUNNING || o->game == OUT_GAME_PAUSED) {
                outputs_game_end(o, now_ms);
            } else {
                all_off(o, "the game is over");
            }
            break;
        case OUT_GAME_NONE:
            if (!o->grace) all_off(o, "no game");
            break;
        case OUT_GAME_PAUSED:
            o->grace = false;
            all_off(o, "the game is paused");
            break;
        case OUT_GAME_HALTED:
            o->grace = false;
            all_off(o, "the mode's script was halted");
            break;
        }
        o->game = game;
    }
    if (o->grace && at_or_after(now_ms, o->grace_until)) {
        o->grace = false;
        all_off(o, "the end's grace is over");
    }
    for (int i = 0; i < o->count; i++) {
        out_channel_t *c = &o->ch[i];
        if (c->on && at_or_after(now_ms, c->until_ms)) c->on = false; /* its time is up */
        update_level(c, now_ms);
        bool live = c->level || (o->game == OUT_GAME_RUNNING && c->set.enabled);
        if (c->be.drive != NULL) c->be.drive(c->be.ctx, c->level, live, now_ms);
    }
}

/* ---- Switching -------------------------------------------------------------------- */

int outputs_find(const outputs_t *o, const char *id)
{
    if (id == NULL) return -1;
    for (int i = 0; i < o->count; i++) {
        if (strcmp(o->ch[i].id, id) == 0) return i;
    }
    return -1;
}

/* May this source switch an output on now (EXP-27, EXP-29)? */
static bool may_start(const outputs_t *o, out_source_t src)
{
    if (src == OUT_SRC_BOX_ADMIN) return o->game == OUT_GAME_NONE && !o->grace;
    return o->game == OUT_GAME_RUNNING || o->grace;
}

static out_result_t start(outputs_t *o, out_channel_t *c, out_act_t act, uint32_t ms,
                          uint32_t on_ms, uint32_t off_ms, out_source_t src)
{
    uint32_t now = o->now;
    if (!c->set.enabled) return OUT_DISABLED;
    if (!may_start(o, src)) return OUT_NOT_NOW;
    uint32_t max_ms = c->set.max_on_s * 1000u;
    if (act == OUT_ACT_ON) {
        if (ms == 0 || ms > max_ms) ms = max_ms;
    } else {
        if (ms == 0 || ms > OUT_MS_MAX) return OUT_BAD_ARGS;
        if (ms > max_ms) ms = max_ms;
    }
    if (act == OUT_ACT_PATTERN) {
        /* A simple output's switch needs a few frames, and a relay should not chatter. */
        if (on_ms < OUT_SIMPLE_MIN_MS || off_ms < OUT_SIMPLE_MIN_MS || on_ms > OUT_PATTERN_MAX_MS ||
            off_ms > OUT_PATTERN_MAX_MS) {
            return OUT_BAD_ARGS;
        }
    }
    if (ms < OUT_SIMPLE_MIN_MS) ms = OUT_SIMPLE_MIN_MS; /* the shortest a switch shows */
    if (o->grace && src != OUT_SRC_BOX_ADMIN) {
        uint32_t left = o->grace_until - now;
        if (left < OUT_SIMPLE_MIN_MS) return OUT_NOT_NOW;
        if (ms > left) ms = left;
    }
    /* Off to on: not within OUT_SIMPLE_MIN_MS of the last change (an off is never held back). */
    if (!c->level && c->changed && now - c->change_ms < OUT_SIMPLE_MIN_MS) return OUT_TOO_SOON;
    if (src == OUT_SRC_SCRIPT) {
        if (c->start_count >= OUT_SCRIPT_STARTS && now - c->starts[c->start_next] < 1000u) {
            if (!c->rate_told) {
                c->rate_told = true;
                char data[128];
                snprintf(data, sizeof(data),
                         "{\"message\":\"output %s: more than %d starts a second, dropped\"}",
                         c->id, OUT_SCRIPT_STARTS);
                tell(o, "script.error", data);
            }
            return OUT_RATE;
        }
        c->starts[c->start_next] = now;
        c->start_next = (uint8_t)((c->start_next + 1) % OUT_SCRIPT_STARTS);
        if (c->start_count < OUT_SCRIPT_STARTS) c->start_count++;
    }
    c->on = true;
    c->pattern = act == OUT_ACT_PATTERN;
    c->on_ms = c->pattern ? on_ms : 0;
    c->off_ms = c->pattern ? off_ms : 0;
    /* A pattern restarted while on keeps going from its on phase, so it changes nothing now. */
    c->start_ms = now;
    c->until_ms = now + ms;
    c->src = src;
    update_level(c, now);
    char data[112];
    snprintf(data, sizeof(data), "{\"capability\":\"%s\",\"ms\":%lu,\"source\":\"%s\"}", c->id,
             (unsigned long)ms, outputs_source_name(src));
    tell(o, "output.switched", data);
    static const char *const acts[] = {"on", "off", "pulse", "pattern"};
    if (c->pattern) {
        say(o, "output %s: pattern %lu/%lu ms for %lu ms (%s)", c->id, (unsigned long)on_ms,
            (unsigned long)off_ms, (unsigned long)ms, outputs_source_name(src));
    } else {
        say(o, "output %s: %s for %lu ms (%s)", c->id, acts[act], (unsigned long)ms,
            outputs_source_name(src));
    }
    return OUT_OK;
}

out_result_t outputs_switch(outputs_t *o, const char *id, out_act_t act, uint32_t ms,
                            uint32_t on_ms, uint32_t off_ms, out_source_t src)
{
    if (id != NULL && strcmp(id, "*") == 0) {
        if (act != OUT_ACT_OFF) return OUT_BAD_ARGS;
        for (int i = 0; i < o->count; i++) turn_off(o, &o->ch[i], src, true);
        return OUT_OK;
    }
    int i = outputs_find(o, id);
    if (i < 0) return OUT_NO_SUCH; /* a mode written for a box with a siren runs on one without */
    out_channel_t *c = &o->ch[i];
    if (act == OUT_ACT_OFF) {
        turn_off(o, c, src, true);
        return OUT_OK;
    }
    out_result_t r = start(o, c, act, ms, on_ms, off_ms, src);
    if (r != OUT_OK && r != OUT_RATE) {
        say(o, "output %s: refused (%s, %s)", c->id, outputs_result_name(r),
            outputs_source_name(src));
    }
    return r;
}

out_result_t outputs_test(outputs_t *o, int index)
{
    if (index < 0 || index >= o->count) return OUT_NO_SUCH;
    return outputs_switch(o, o->ch[index].id, OUT_ACT_PULSE, OUT_TEST_MS, 0, 0, OUT_SRC_BOX_ADMIN);
}

/* ---- CMD 12 ------------------------------------------------------------------------- */

/* key's value: absent (0), a number (1, *v set), anything else (-1). */
static int number_of(const char *json, const char *key, double *v)
{
    if (!screen_json_has(json, key)) return 0;
    return screen_json_number(json, key, v) ? 1 : -1;
}

static bool whole_in(double v, double lo, double hi)
{
    return v >= lo && v <= hi && floor(v) == v;
}

const char *outputs_cmd_problem(const char *params_json)
{
    if (params_json == NULL || params_json[0] != '{') return "params is a map";
    char cap[OUT_ID_MAX + 2], act[12], src[8];
    if (!screen_json_str(params_json, "capability", cap, sizeof(cap))) {
        return "capability is required";
    }
    if (strcmp(cap, "*") != 0 && !outputs_id_ok(cap)) {
        return "a capability id is 1-23 bytes of a-z 0-9 . _ -";
    }
    if (!screen_json_str(params_json, "act", act, sizeof(act)) ||
        (strcmp(act, "on") != 0 && strcmp(act, "off") != 0 && strcmp(act, "pulse") != 0 &&
         strcmp(act, "pattern") != 0)) {
        return "act is on, off, pulse or pattern";
    }
    if (!screen_json_str(params_json, "src", src, sizeof(src)) ||
        (strcmp(src, "field") != 0 && strcmp(src, "gm") != 0)) {
        return "src is field or gm";
    }
    if (strcmp(cap, "*") == 0 && strcmp(act, "off") != 0) return "* only with off";
    if (strcmp(act, "off") == 0) return NULL;
    double ms;
    int has = number_of(params_json, "ms", &ms);
    if (has == 0) return "ms is required for on, pulse and pattern";
    if (has < 0 || floor(ms) != ms) return "ms is an integer";
    if (!whole_in(ms, 1, OUT_MS_MAX)) return "ms is 1 to 600000";
    if (strcmp(act, "pattern") == 0) {
        double on_ms, off_ms;
        int has_on = number_of(params_json, "on_ms", &on_ms);
        int has_off = number_of(params_json, "off_ms", &off_ms);
        if (has_on == 0 || has_off == 0) return "on_ms and off_ms are required for pattern";
        if (has_on < 0 || has_off < 0 || !whole_in(on_ms, OUT_PATTERN_MIN_MS, OUT_PATTERN_MAX_MS) ||
            !whole_in(off_ms, OUT_PATTERN_MIN_MS, OUT_PATTERN_MAX_MS)) {
            return "on_ms and off_ms are 10 to 10000";
        }
    }
    return NULL;
}

out_result_t outputs_cmd(outputs_t *o, const char *params_json, const char **why)
{
    const char *problem = outputs_cmd_problem(params_json);
    if (why != NULL) *why = problem;
    if (problem != NULL) {
        say(o, "CMD output refused: %s", problem);
        return OUT_BAD_ARGS;
    }
    char cap[OUT_ID_MAX + 2], act[12], src[8];
    screen_json_str(params_json, "capability", cap, sizeof(cap));
    screen_json_str(params_json, "act", act, sizeof(act));
    screen_json_str(params_json, "src", src, sizeof(src));
    double ms = 0, on_ms = 0, off_ms = 0;
    screen_json_number(params_json, "ms", &ms);
    screen_json_number(params_json, "on_ms", &on_ms);
    screen_json_number(params_json, "off_ms", &off_ms);
    out_act_t a = strcmp(act, "on") == 0      ? OUT_ACT_ON
                  : strcmp(act, "off") == 0   ? OUT_ACT_OFF
                  : strcmp(act, "pulse") == 0 ? OUT_ACT_PULSE
                                              : OUT_ACT_PATTERN;
    out_source_t s = strcmp(src, "gm") == 0 ? OUT_SRC_GM : OUT_SRC_FIELD;
    out_result_t r = outputs_switch(o, cap, a, (uint32_t)ms, (uint32_t)on_ms, (uint32_t)off_ms, s);
    if (r == OUT_NO_SUCH) say(o, "CMD output: this box has no output %s (ignored)", cap);
    return r;
}

/* ---- What the box tells --------------------------------------------------------------- */

int outputs_enabled_count(const outputs_t *o)
{
    int n = 0;
    for (int i = 0; i < o->count; i++) n += o->ch[i].set.enabled ? 1 : 0;
    return n;
}

size_t outputs_modules_text(const outputs_t *o, char *out, size_t cap)
{
    if (cap == 0) return 0;
    out[0] = '\0';
    size_t len = 0;
    size_t limit = cap - 1 < OUT_MODULES_MAX ? cap - 1 : OUT_MODULES_MAX;
    for (int i = 0; i < o->count; i++) {
        const out_channel_t *c = &o->ch[i];
        if (!c->set.enabled) continue;
        char entry[48];
        int n = snprintf(entry, sizeof(entry), "%sg%d:servo:%s", len ? ";" : "", c->gpio, c->id);
        if (n < 0 || len + (size_t)n > limit) break;
        memcpy(out + len, entry, (size_t)n + 1);
        len += (size_t)n;
    }
    return len;
}

bool outputs_level(const outputs_t *o, int index)
{
    return index >= 0 && index < o->count && o->ch[index].level;
}
