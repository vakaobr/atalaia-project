/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's settings pushed over the radio (see pod_settings.h).
 */
#include "pod_settings.h"

#include <stdio.h>
#include <string.h>

/* The names a button's colour may take: those pod_caps_team_rgb() paints (and IDENT carries). */
static const char *const colour_names[] = {"red",    "blue",  "green", "yellow", "orange",
                                           "purple", "white", "pink",  "cyan"};

static bool colour_ok(const char *c)
{
    if (c[0] == '\0') return true; /* the game's N-th team */
    for (size_t i = 0; i < sizeof(colour_names) / sizeof(colour_names[0]); i++) {
        if (strcmp(c, colour_names[i]) == 0) return true;
    }
    return false;
}

/* ---- A strict reader of compact JSON: no spaces, no escapes, only what the command has ---- */

typedef struct {
    const char *p;
} rd_t;

static bool eat(rd_t *r, char c)
{
    if (*r->p != c) return false;
    r->p++;
    return true;
}

static bool rd_string(rd_t *r, char *out, size_t cap)
{
    if (!eat(r, '"')) return false;
    size_t n = 0;
    while (*r->p != '"') {
        unsigned char c = (unsigned char)*r->p;
        if (c < 0x20 || c == '\\' || c >= 0x7F || n + 1 >= cap) return false;
        out[n++] = (char)c;
        r->p++;
    }
    out[n] = '\0';
    r->p++;
    return true;
}

static bool rd_uint(rd_t *r, uint32_t max, uint32_t *out)
{
    if (*r->p < '0' || *r->p > '9') return false;
    if (r->p[0] == '0' && r->p[1] >= '0' && r->p[1] <= '9') return false; /* no leading zero */
    uint64_t v = 0;
    while (*r->p >= '0' && *r->p <= '9') {
        v = v * 10 + (uint64_t)(*r->p - '0');
        if (v > max) return false;
        r->p++;
    }
    *out = (uint32_t)v;
    return true;
}

static bool rd_bool(rd_t *r, bool *out)
{
    if (strncmp(r->p, "true", 4) == 0) {
        r->p += 4;
        *out = true;
        return true;
    }
    if (strncmp(r->p, "false", 5) == 0) {
        r->p += 5;
        *out = false;
        return true;
    }
    return false;
}

bool pod_settings_parse(const char *json, pod_settings_cmd_t *out)
{
    memset(out, 0, sizeof(*out));
    if (json == NULL) return false;
    rd_t r = {json};
    if (!eat(&r, '{')) return false;
    uint32_t seen = 0; /* one bit per key: a repeated key is refused */
    bool have_v = false;
    uint32_t v = 0;
    while (*r.p != '}') {
        if (seen != 0 && !eat(&r, ',')) return false;
        char key[12];
        if (!rd_string(&r, key, sizeof(key)) || !eat(&r, ':')) return false;
        uint32_t bit;
        uint32_t n = 0;
        bool b = false;
        if (strcmp(key, "v") == 0) {
            bit = 1u << 0;
            if (!rd_uint(&r, 65535, &v)) return false;
            have_v = true;
        } else if (strcmp(key, "rev") == 0) {
            bit = 1u << 1;
            if (!rd_uint(&r, 0xFFFFFFFFu, &out->rev)) return false;
        } else if (strcmp(key, "reset") == 0) {
            bit = 1u << 2;
            if (!rd_bool(&r, &b)) return false;
            out->reset = b;
        } else if (strcmp(key, "btn") == 0) {
            bit = 1u << 3;
            if (!eat(&r, '[')) return false;
            for (int i = 0; i < POD_BUTTONS; i++) {
                if (i > 0 && !eat(&r, ',')) return false;
                if (!rd_string(&r, out->btn[i], sizeof(out->btn[i])) || !colour_ok(out->btn[i])) {
                    return false;
                }
            }
            if (!eat(&r, ']')) return false;
            out->set |= POD_SET_BTN;
        } else if (strcmp(key, "bright") == 0) {
            bit = 1u << 4;
            if (!rd_uint(&r, 100, &n)) return false;
            out->bright = (uint8_t)n;
            out->set |= POD_SET_BRIGHT;
        } else if (strcmp(key, "vol") == 0) {
            bit = 1u << 5;
            if (!rd_uint(&r, 100, &n)) return false;
            out->vol = (uint8_t)n;
            out->set |= POD_SET_VOL;
        } else if (strcmp(key, "tamper") == 0) {
            bit = 1u << 6;
            if (!rd_bool(&r, &b)) return false;
            out->tamper = b;
            out->set |= POD_SET_TAMPER;
        } else {
            return false; /* a key of this version that the pod does not know */
        }
        if (seen & bit) return false;
        seen |= bit;
    }
    r.p++;
    if (*r.p != '\0') return false;
    /* v and rev are required; rev 0 is "nothing pushed yet", never a push. */
    if (!have_v || v != POD_SETTINGS_VERSION || !(seen & (1u << 1)) || out->rev == 0) return false;
    return true;
}

/* ---- Stored form ------------------------------------------------------------------------ */

size_t pod_settings_to_json(const pod_settings_t *s, char *out, size_t cap)
{
    size_t n = 0;
    int w =
        snprintf(out, cap, "{\"v\":%d,\"rev\":%lu", POD_SETTINGS_VERSION, (unsigned long)s->rev);
    if (w < 0 || (size_t)w >= cap) return 0;
    n = (size_t)w;
    if (s->set & POD_SET_BTN) {
        w = snprintf(out + n, cap - n, ",\"btn\":[\"%s\",\"%s\",\"%s\",\"%s\"]", s->btn[0],
                     s->btn[1], s->btn[2], s->btn[3]);
        if (w < 0 || (size_t)w >= cap - n) return 0;
        n += (size_t)w;
    }
    if (s->set & POD_SET_BRIGHT) {
        w = snprintf(out + n, cap - n, ",\"bright\":%u", (unsigned)s->bright);
        if (w < 0 || (size_t)w >= cap - n) return 0;
        n += (size_t)w;
    }
    if (s->set & POD_SET_VOL) {
        w = snprintf(out + n, cap - n, ",\"vol\":%u", (unsigned)s->vol);
        if (w < 0 || (size_t)w >= cap - n) return 0;
        n += (size_t)w;
    }
    if (s->set & POD_SET_TAMPER) {
        w = snprintf(out + n, cap - n, ",\"tamper\":%s", s->tamper ? "true" : "false");
        if (w < 0 || (size_t)w >= cap - n) return 0;
        n += (size_t)w;
    }
    if (n + 2 > cap) return 0;
    out[n++] = '}';
    out[n] = '\0';
    return n;
}

static void merge(pod_settings_t *s, const pod_settings_cmd_t *c)
{
    if (c->reset) memset(s, 0, sizeof(*s));
    s->rev = c->rev;
    if (c->set & POD_SET_BTN) memcpy(s->btn, c->btn, sizeof(s->btn));
    if (c->set & POD_SET_BRIGHT) s->bright = c->bright;
    if (c->set & POD_SET_VOL) s->vol = c->vol;
    if (c->set & POD_SET_TAMPER) s->tamper = c->tamper;
    s->set = (uint8_t)((c->reset ? 0 : s->set) | c->set);
}

void pod_settings_load(pod_settings_t *s, const char *json)
{
    memset(s, 0, sizeof(*s));
    pod_settings_cmd_t c;
    if (json != NULL && pod_settings_parse(json, &c)) merge(s, &c);
}

/* ---- Handling a command ------------------------------------------------------------------ */

pod_config_result_t pod_settings_handle(pod_settings_t *s, const char *json, pod_caps_t *caps,
                                        const pod_caps_config_t *build, uint32_t *rev)
{
    pod_settings_cmd_t c;
    if (!pod_settings_parse(json, &c)) return POD_CONFIG_REFUSED;
    if (c.rev < s->rev) return POD_CONFIG_STALE;
    *rev = c.rev;
    if (c.rev == s->rev) return POD_CONFIG_SAME;
    merge(s, &c);
    pod_settings_apply(s, caps, build);
    return POD_CONFIG_APPLIED;
}

void pod_settings_apply(const pod_settings_t *s, pod_caps_t *caps, const pod_caps_config_t *build)
{
    for (int i = 0; i < POD_BUTTONS; i++) {
        if (s->set & POD_SET_BTN) {
            caps->cfg.team[i] = s->btn[i][0] != '\0' ? s->btn[i] : NULL;
        } else {
            caps->cfg.team[i] = build->team[i];
        }
    }
    /* A switch that is not fitted is never turned on. */
    bool tamper = (s->set & POD_SET_TAMPER) ? (s->tamper && build->tamper) : build->tamper;
    if (caps->cfg.tamper && !tamper) {
        caps->tamper_armed = false;
        caps->tamper_open = false;
    }
    caps->cfg.tamper = tamper;

    uint8_t bright = (s->set & POD_SET_BRIGHT) ? s->bright : 100;
    caps->brightness = bright;
    if (caps->cfg.leds && caps->hal != NULL && caps->hal->leds != NULL) {
        caps->hal->leds->set_brightness(bright);
    }
    /* The volume has no default of its own here (the audio HAL's): a pushed one is applied;
     * dropping it takes effect at the next restart. */
    if ((s->set & POD_SET_VOL) && caps->cfg.audio && caps->audio.volume != NULL) {
        caps->audio.volume(caps->audio.ctx, s->vol);
    }
}
