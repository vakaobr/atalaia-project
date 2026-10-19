/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's capabilities (see pod_caps.h).
 */
#include "pod_caps.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"
#include "atalaia/tag.h"
#include "pod_json.h"

void pod_caps_init(pod_caps_t *c, const pod_caps_config_t *cfg, const hal_t *hal,
                   const pod_audio_t *audio)
{
    memset(c, 0, sizeof(*c));
    c->cfg = *cfg;
    c->hal = hal;
    if (audio != NULL) c->audio = *audio;
    c->tamper_raw = -2; /* nothing read yet */
    c->brightness = 100;
    key_filter_init(&c->keys);
    if (hal == NULL || hal->buttons == NULL) {
        for (int i = 0; i < POD_BUTTONS; i++) c->cfg.button[i] = false;
    }
    if (hal == NULL || hal->keypad == NULL) c->cfg.keypad = false;
    if (hal == NULL || hal->nfc == NULL) c->cfg.nfc = false;
    if (hal == NULL || hal->leds == NULL || c->cfg.led_count == 0) c->cfg.leds = false;
    if (audio == NULL || audio->tone == NULL) c->cfg.audio = false;
}

/* ---- Descriptors ----------------------------------------------------------------- */

static bool add(char *out, size_t cap, size_t *n, const char *item)
{
    size_t len = strlen(item);
    if (*n + len + 2 > cap) return false;
    if (*n > 1) out[(*n)++] = ',';
    memcpy(out + *n, item, len);
    *n += len;
    return true;
}

size_t pod_caps_descriptors(const pod_caps_t *c, char *out, size_t cap, bool with_teams)
{
    if (cap < 3) return 0;
    size_t n = 0;
    out[n++] = '[';
    char item[96];
    bool ok = true;
    for (int i = 0; i < POD_BUTTONS && ok; i++) {
        if (!c->cfg.button[i]) continue;
        if (with_teams && c->cfg.team[i] != NULL && c->cfg.team[i][0] != '\0') {
            snprintf(item, sizeof(item),
                     "{\"id\":\"btn.%d\",\"type\":\"button\",\"team\":\"%.23s\"}", i + 1,
                     c->cfg.team[i]);
        } else {
            snprintf(item, sizeof(item), "{\"id\":\"btn.%d\",\"type\":\"button\"}", i + 1);
        }
        ok = add(out, cap, &n, item);
    }
    if (ok && c->cfg.keypad) ok = add(out, cap, &n, "{\"id\":\"keypad\",\"type\":\"keypad\"}");
    if (ok && c->cfg.leds) {
        snprintf(item, sizeof(item), "{\"id\":\"ring\",\"type\":\"led\",\"count\":%u}",
                 (unsigned)c->cfg.led_count);
        ok = add(out, cap, &n, item);
    }
    if (ok && c->cfg.audio) ok = add(out, cap, &n, "{\"id\":\"audio\",\"type\":\"audio\"}");
    if (ok && c->cfg.nfc) ok = add(out, cap, &n, "{\"id\":\"nfc\",\"type\":\"nfc\"}");
    if (ok && c->cfg.tamper) ok = add(out, cap, &n, "{\"id\":\"case\",\"type\":\"tamper\"}");
    if (!ok || n + 2 > cap) return 0;
    out[n++] = ']';
    out[n] = '\0';
    return n;
}

/* ---- Inputs ---------------------------------------------------------------------- */

static void emit_ms(pod_emit_fn emit, void *ctx, int button, const char *event, uint32_t ms)
{
    char id[16], data[32];
    snprintf(id, sizeof(id), "btn.%d", button + 1);
    snprintf(data, sizeof(data), "{\"ms\":%lu}", (unsigned long)ms);
    emit(ctx, id, event, data);
}

static void poll_buttons(pod_caps_t *c, uint32_t delta, pod_emit_fn emit, void *ctx)
{
    uint8_t mask = c->hal->buttons->poll();
    for (int i = 0; i < POD_BUTTONS; i++) {
        if (!c->cfg.button[i]) continue;
        bool down = (mask >> i) & 1;
        if (down && !c->pressed[i]) {
            c->pressed[i] = true;
            c->held_ms[i] = 0;
            c->since_hold[i] = 0;
            char id[16];
            snprintf(id, sizeof(id), "btn.%d", i + 1);
            emit(ctx, id, "press", "");
        } else if (down) {
            c->held_ms[i] += delta;
            c->since_hold[i] += delta;
            while (c->since_hold[i] >= POD_HOLD_INTERVAL_MS) {
                c->since_hold[i] -= POD_HOLD_INTERVAL_MS;
                emit_ms(emit, ctx, i, "hold", c->held_ms[i] - c->since_hold[i]);
            }
        } else if (c->pressed[i]) {
            c->pressed[i] = false;
            c->held_ms[i] += delta;
            emit_ms(emit, ctx, i, "release", c->held_ms[i]);
        }
    }
}

static void poll_keypad(pod_caps_t *c, pod_emit_fn emit, void *ctx)
{
    if (c->now_ms - c->last_scan_ms < POD_KEY_SCAN_MS) return;
    c->last_scan_ms = c->now_ms;
    char k = key_filter_update(&c->keys, c->hal->keypad->scan());
    if (k == HAL_KEY_NONE) return;
    char data[16];
    snprintf(data, sizeof(data), "{\"key\":\"%c\"}", k);
    emit(ctx, "keypad", "key", data);
}

static void hex(const uint8_t *b, size_t n, char *out)
{
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) {
        out[2 * i] = digits[b[i] >> 4];
        out[2 * i + 1] = digits[b[i] & 0x0F];
    }
    out[2 * n] = '\0';
}

static void poll_nfc(pod_caps_t *c, pod_emit_fn emit, void *ctx)
{
    if (c->now_ms - c->last_nfc_ms < POD_NFC_POLL_MS && c->last_nfc_ms != 0) return;
    c->last_nfc_ms = c->now_ms == 0 ? 1 : c->now_ms;
    hal_nfc_tag_t tag;
    if (!c->hal->nfc->poll(&tag)) {
        c->last_uid_len = 0; /* the card was taken away */
        return;
    }
    if (tag.uid_len == c->last_uid_len && memcmp(tag.uid, c->last_uid, tag.uid_len) == 0) {
        return; /* the same card is still on the reader: once per tap */
    }
    if (tag.uid_len == 0 || tag.uid_len > sizeof(c->last_uid)) return;
    memcpy(c->last_uid, tag.uid, tag.uid_len);
    c->last_uid_len = tag.uid_len;
    int n = c->hal->nfc->read_user_memory != NULL
                ? c->hal->nfc->read_user_memory(c->mem, sizeof(c->mem))
                : -1;
    const uint8_t *record = NULL;
    size_t len = n > 0 ? atalaia_tag_from_ndef_tag(c->mem, (size_t)n, &record) : 0;
    if (len > ATALAIA_TAG_MAX) len = 0;
    const uint8_t *join = NULL;
    if (len == 0 && n > 0 && atalaia_join_from_ndef_tag(c->mem, (size_t)n, &join) > 0) {
        return; /* a join card: the phone joins by QR code or text */
    }
    char uid[2 * 10 + 1], rec[2 * ATALAIA_TAG_MAX + 1], data[2 * 10 + 2 * ATALAIA_TAG_MAX + 32];
    hex(tag.uid, tag.uid_len, uid);
    if (len > 0) {
        hex(record, len, rec);
        snprintf(data, sizeof(data), "{\"uid\":\"%s\",\"tag\":\"%s\"}", uid, rec);
    } else {
        snprintf(data, sizeof(data), "{\"uid\":\"%s\"}", uid);
    }
    emit(ctx, "nfc", "tag", data);
}

static void poll_tamper(pod_caps_t *c, int raw, pod_emit_fn emit, void *ctx)
{
    if (raw < 0) return;
    raw = raw ? 1 : 0;
    if (raw != c->tamper_raw) {
        c->tamper_raw = raw;
        c->tamper_since_ms = c->now_ms;
        return;
    }
    if (c->now_ms - c->tamper_since_ms < POD_TAMPER_DEBOUNCE_MS) return;
    bool open = raw == 1;
    if (!open) {
        bool was_open = c->tamper_open && c->tamper_armed;
        c->tamper_armed = true;
        c->tamper_open = false;
        if (was_open) emit(ctx, "case", "closed", "");
        return;
    }
    if (c->tamper_open) return;
    c->tamper_open = true;
    if (c->tamper_armed) emit(ctx, "case", "opened", "");
}

void pod_caps_poll(pod_caps_t *c, uint32_t now_ms, int tamper_raw, pod_emit_fn emit, void *ctx)
{
    uint32_t delta = c->started ? now_ms - c->now_ms : 0;
    c->started = true;
    c->now_ms = now_ms;
    if (c->cfg.button[0] || c->cfg.button[1] || c->cfg.button[2] || c->cfg.button[3]) {
        poll_buttons(c, delta, emit, ctx);
    }
    if (c->cfg.keypad) poll_keypad(c, emit, ctx);
    if (c->cfg.nfc) poll_nfc(c, emit, ctx);
    if (c->cfg.tamper) poll_tamper(c, tamper_raw, emit, ctx);
}

void pod_caps_report(pod_caps_t *c, pod_emit_fn emit, void *ctx)
{
    if (c->cfg.tamper && c->tamper_armed && c->tamper_open) emit(ctx, "case", "opened", "");
}

/* ---- Commands -------------------------------------------------------------------- */

typedef struct {
    const char *name;
    uint8_t r, g, b;
} team_colour_t;

/* The team colours (the boxes' and the app's names; RFC 0001 team names are colours). */
static const team_colour_t colours[] = {
    {"red", 255, 0, 0},       {"blue", 0, 0, 255},     {"green", 0, 255, 0},
    {"yellow", 255, 255, 0},  {"orange", 255, 128, 0}, {"purple", 128, 0, 255},
    {"white", 255, 255, 255}, {"pink", 255, 64, 160},  {"cyan", 0, 255, 255},
    {"none", 0, 0, 0},        {"off", 0, 0, 0},        {"black", 0, 0, 0},
};

void pod_caps_team_rgb(const char *team, uint8_t rgb[3])
{
    for (size_t i = 0; i < sizeof(colours) / sizeof(colours[0]); i++) {
        if (team != NULL && strcmp(team, colours[i].name) == 0) {
            rgb[0] = colours[i].r;
            rgb[1] = colours[i].g;
            rgb[2] = colours[i].b;
            return;
        }
    }
    rgb[0] = rgb[1] = rgb[2] = 255; /* a team without a known colour: white */
}

static uint8_t byte_of(double v)
{
    return v <= 0 ? 0 : v >= 255 ? 255 : (uint8_t)(v + 0.5);
}

/* r, g, b from {"r","g","b"} or {"args":[r,g,b]}. */
static bool read_rgb(const char *json, uint8_t rgb[3])
{
    double v[3];
    bool named = pod_json_num(json, "r", &v[0]) && pod_json_num(json, "g", &v[1]) &&
                 pod_json_num(json, "b", &v[2]);
    if (!named && !(pod_json_arg_num(json, 0, &v[0]) && pod_json_arg_num(json, 1, &v[1]) &&
                    pod_json_arg_num(json, 2, &v[2]))) {
        return false;
    }
    for (int i = 0; i < 3; i++) rgb[i] = byte_of(v[i]);
    return true;
}

/* A number from a named key or from args[0]. */
static bool read_value(const char *json, const char *key, double *v)
{
    return pod_json_num(json, key, v) || pod_json_arg_num(json, 0, v);
}

static void ring_fill(pod_caps_t *c, const uint8_t rgb[3])
{
    memcpy(c->fill, rgb, 3);
    c->hal->leds->fill(rgb[0], rgb[1], rgb[2]);
    c->hal->leds->show();
}

static bool ring_command(pod_caps_t *c, const char *method, const char *args)
{
    uint8_t rgb[3];
    double v;
    char team[24];
    if (strcmp(method, "fill") == 0 || strcmp(method, "color") == 0) {
        if (pod_json_str(args, "team", team, sizeof(team)) ||
            pod_json_arg_str(args, 0, team, sizeof(team))) {
            pod_caps_team_rgb(team, rgb);
        } else if (!read_rgb(args, rgb)) {
            return false;
        }
        ring_fill(c, rgb);
        return true;
    }
    if (strcmp(method, "off") == 0) {
        const uint8_t black[3] = {0, 0, 0};
        ring_fill(c, black);
        return true;
    }
    if (strcmp(method, "set_brightness") == 0 || strcmp(method, "brightness") == 0) {
        if (!read_value(args, "pct", &v)) return false;
        c->brightness = (uint8_t)(v <= 0 ? 0 : v >= 100 ? 100 : v + 0.5);
        c->hal->leds->set_brightness(c->brightness);
        c->hal->leds->show();
        return true;
    }
    if (strcmp(method, "progress") == 0) {
        if (!read_value(args, "value", &v)) return false;
        if (v < 0) v = 0;
        if (v > 1) v = 1;
        int lit = (int)(v * c->cfg.led_count + 0.5);
        uint8_t on[3] = {c->fill[0], c->fill[1], c->fill[2]};
        if ((on[0] | on[1] | on[2]) == 0) on[0] = on[1] = on[2] = 255;
        for (int i = 0; i < c->cfg.led_count; i++) {
            if (i < lit) {
                c->hal->leds->set(i, on[0], on[1], on[2]);
            } else {
                c->hal->leds->set(i, 0, 0, 0);
            }
        }
        c->hal->leds->show();
        return true;
    }
    return false;
}

typedef struct {
    uint16_t hz, ms;
} tone_step_t;

/* The pod has no sound files: the mode's clips are played as tones (PF7). */
static const struct {
    const char *clip;
    tone_step_t steps[6];
} clips[] = {
    {"explosion", {{120, 1500}}},
    {"armed", {{1000, 150}, {0, 100}, {1000, 150}}},
    {"defused", {{1500, 150}, {2000, 250}}},
    {"captured", {{1200, 150}, {1600, 200}}},
    {"alarm", {{2500, 300}, {0, 150}, {2500, 300}, {0, 150}, {2500, 300}}},
    {"tick", {{3000, 30}}},
};

static void play_clip(pod_caps_t *c, const char *clip)
{
    for (size_t i = 0; i < sizeof(clips) / sizeof(clips[0]); i++) {
        if (strcmp(clip, clips[i].clip) != 0) continue;
        for (size_t s = 0; s < 6 && clips[i].steps[s].ms > 0; s++) {
            c->audio.tone(c->audio.ctx, clips[i].steps[s].hz, clips[i].steps[s].ms);
        }
        return;
    }
    c->audio.tone(c->audio.ctx, 2000, 120); /* any other clip: a beep */
}

static bool audio_command(pod_caps_t *c, const char *method, const char *args)
{
    double v, ms;
    char clip[32];
    if (strcmp(method, "tone") == 0) {
        if (!(pod_json_num(args, "freq", &v) && pod_json_num(args, "ms", &ms)) &&
            !(pod_json_arg_num(args, 0, &v) && pod_json_arg_num(args, 1, &ms))) {
            return false;
        }
        uint32_t hz = v <= 0 ? 0 : v >= 20000 ? 20000 : (uint32_t)v;
        uint32_t len = ms < 1 ? 1 : ms > 10000 ? 10000 : (uint32_t)ms;
        c->audio.tone(c->audio.ctx, hz, len);
        return true;
    }
    if (strcmp(method, "play") == 0) {
        if (!pod_json_arg_str(args, 0, clip, sizeof(clip)) &&
            !pod_json_str(args, "clip", clip, sizeof(clip))) {
            return false;
        }
        play_clip(c, clip);
        return true;
    }
    if (strcmp(method, "stop") == 0) {
        if (c->audio.stop != NULL) c->audio.stop(c->audio.ctx);
        return true;
    }
    if (strcmp(method, "set_volume") == 0 || strcmp(method, "volume") == 0) {
        if (!read_value(args, "pct", &v)) return false;
        if (c->audio.volume != NULL) {
            c->audio.volume(c->audio.ctx, (uint8_t)(v <= 0 ? 0 : v >= 100 ? 100 : v + 0.5));
        }
        return true;
    }
    return false;
}

bool pod_caps_command(pod_caps_t *c, const atalaia_proxy_msg_t *m)
{
    bool ok = false;
    if (strcmp(m->cap_id, "ring") == 0 && c->cfg.leds) {
        ok = ring_command(c, m->name, m->data_json);
    } else if (strcmp(m->cap_id, "audio") == 0 && c->cfg.audio) {
        ok = audio_command(c, m->name, m->data_json);
    } else if (strcmp(m->cap_id, "keypad") == 0 && c->cfg.keypad) {
        ok = strcmp(m->name, "clear") == 0; /* the pod keeps no code of its own */
    }
    if (!ok) c->commands_unknown++;
    return ok;
}
