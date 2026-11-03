/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "command_dispatch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "sound.h"

void command_queues_init(command_queues_t *q)
{
    memset(q, 0, sizeof(*q));
}

/* Simple JSON string extraction: find "template" at position 1 in a JSON array.
 * Input like: ["countdown",{"left":42}]
 * Extracts the first string into name, the rest into data. */
static void parse_screen_args(const char *args, char *name, size_t name_sz, char *data,
                              size_t data_sz)
{
    name[0] = '\0';
    data[0] = '\0';
    if (!args || args[0] != '[') return;

    /* Find the first quoted string. */
    const char *q1 = strchr(args, '"');
    if (!q1) return;
    q1++;
    const char *q2 = strchr(q1, '"');
    if (!q2) return;

    size_t len = (size_t)(q2 - q1);
    if (len >= name_sz) len = name_sz - 1;
    memcpy(name, q1, len);
    name[len] = '\0';

    /* The data is everything after the comma following the closing quote. */
    const char *comma = strchr(q2, ',');
    if (comma) {
        comma++;
        while (*comma == ' ') comma++;
        /* Find the last ']' and copy up to (but not including) it. */
        const char *end = strrchr(comma, ']');
        if (end) {
            size_t dlen = (size_t)(end - comma);
            if (dlen >= data_sz) dlen = data_sz - 1;
            memcpy(data, comma, dlen);
            data[dlen] = '\0';
        }
    }
}

/* Parse first string from args JSON array: ["clip_name"] -> clip_name */
static void parse_first_string(const char *args, char *out, size_t out_sz)
{
    out[0] = '\0';
    if (!args) return;
    const char *q1 = strchr(args, '"');
    if (!q1) return;
    q1++;
    const char *q2 = strchr(q1, '"');
    if (!q2) return;
    size_t len = (size_t)(q2 - q1);
    if (len >= out_sz) len = out_sz - 1;
    memcpy(out, q1, len);
    out[len] = '\0';
}

/* [freq, ms] (audio.tone's arguments) as a tone of at most SOUND_TONE_MAX_HZ and
 * SOUND_TONE_MAX_MS; false when either is missing or not a number. */
static bool parse_tone_args(const char *args, uint16_t *hz, uint16_t *ms)
{
    if (!args || args[0] != '[') return false;
    char *end;
    double f = strtod(args + 1, &end);
    if (end == args + 1) return false;
    while (*end == ' ') end++;
    if (*end != ',') return false;
    const char *second = end + 1;
    double d = strtod(second, &end);
    if (end == second) return false;
    if (!(f >= 0)) f = 0; /* also NaN */
    if (!(d >= 0)) d = 0;
    *hz = (uint16_t)(f > SOUND_TONE_MAX_HZ ? SOUND_TONE_MAX_HZ : f);
    *ms = (uint16_t)(d > SOUND_TONE_MAX_MS ? SOUND_TONE_MAX_MS : d);
    return true;
}

/* Parse a color name to RGB. Simple mapping for team colors. */
static void color_name_to_rgb(const char *name, uint8_t *r, uint8_t *g, uint8_t *b)
{
    if (strcmp(name, "red") == 0) {
        *r = 255;
        *g = 0;
        *b = 0;
    } else if (strcmp(name, "blue") == 0) {
        *r = 0;
        *g = 0;
        *b = 255;
    } else if (strcmp(name, "green") == 0) {
        *r = 0;
        *g = 255;
        *b = 0;
    } else if (strcmp(name, "yellow") == 0) {
        *r = 255;
        *g = 255;
        *b = 0;
    } else if (strcmp(name, "off") == 0 || strcmp(name, "none") == 0) {
        *r = 0;
        *g = 0;
        *b = 0;
    } else {
        *r = 255;
        *g = 255;
        *b = 255;
    }
}

void command_dispatch(const char *target, const char *method, const char *args_json, hal_t *hal,
                      command_queues_t *queues)
{
    if (!target || !method) return;

    if (strcmp(target, "ui") == 0 && strcmp(method, "screen") == 0) {
        if (queues->screen_count < CMD_SCREEN_QUEUE_MAX) {
            screen_update_t *su = &queues->screens[queues->screen_count];
            parse_screen_args(args_json, su->template_name, sizeof(su->template_name),
                              su->data_json, sizeof(su->data_json));
            queues->screen_count++;
        }
        return;
    }

    if (strcmp(target, "audio") == 0) {
        if (strcmp(method, "play") == 0) {
            if (queues->audio_count < CMD_AUDIO_QUEUE_MAX) {
                audio_cmd_t *a = &queues->audio[queues->audio_count];
                memset(a, 0, sizeof(*a));
                parse_first_string(args_json, a->clip, sizeof(a->clip));
                if (a->clip[0] != '\0') queues->audio_count++; /* no clip: not a stop */
            }
        } else if (strcmp(method, "tone") == 0) {
            uint16_t hz, ms;
            if (queues->audio_count < CMD_AUDIO_QUEUE_MAX && parse_tone_args(args_json, &hz, &ms) &&
                ms > 0) {
                audio_cmd_t *a = &queues->audio[queues->audio_count];
                memset(a, 0, sizeof(*a));
                a->tone_hz = hz;
                a->tone_ms = ms;
                queues->audio_count++;
            }
        } else if (strcmp(method, "stop") == 0) {
            if (queues->audio_count < CMD_AUDIO_QUEUE_MAX) {
                memset(&queues->audio[queues->audio_count], 0, sizeof(audio_cmd_t));
                queues->audio_count++;
            }
        }
        return;
    }

    if (strcmp(target, "ring") == 0 && hal && hal->leds) {
        if (strcmp(method, "fill") == 0) {
            char color[32];
            parse_first_string(args_json, color, sizeof(color));
            uint8_t r, g, b;
            color_name_to_rgb(color, &r, &g, &b);
            hal->leds->fill(r, g, b);
            hal->leds->show();
        } else if (strcmp(method, "set_brightness") == 0) {
            /* args: [brightness_value] */
            if (args_json) {
                int val = 0;
                const char *p = args_json;
                while (*p && (*p < '0' || *p > '9')) p++;
                while (*p >= '0' && *p <= '9') {
                    val = val * 10 + (*p - '0');
                    p++;
                }
                hal->leds->set_brightness((uint8_t)(val > 100 ? 100 : val)); /* percent */
            }
        } else if (strcmp(method, "progress") == 0) {
            /* args: [0.5] -- fill fraction of LEDs. Simplified: fill all. */
            hal->leds->show();
        }
        return;
    }

    if (strcmp(target, "team_display") == 0 && hal && hal->leds) {
        if (strcmp(method, "show") == 0) {
            char color[32];
            parse_first_string(args_json, color, sizeof(color));
            uint8_t r, g, b;
            color_name_to_rgb(color, &r, &g, &b);
            hal->leds->fill(r, g, b);
            hal->leds->show();
        }
        return;
    }
}

/* Up to max numbers of a JSON array ("[10000]", "[500,500,20000]"); how many were read. A value
 * that is not a number ends the list. */
static int parse_numbers(const char *args, double *out, int max)
{
    if (!args || args[0] != '[') return 0;
    const char *p = args + 1;
    int n = 0;
    while (n < max) {
        while (*p == ' ') p++;
        char *end;
        double v = strtod(p, &end);
        if (end == p) break;
        out[n++] = v;
        p = end;
        while (*p == ' ') p++;
        if (*p != ',') break;
        p++;
    }
    return n;
}

/* A script's duration: a whole number of ms, at most OUT_MS_MAX (0 when not given or < 1). */
static uint32_t script_ms(const double *v, int n, int i)
{
    if (i >= n || !(v[i] >= 1)) return 0;
    return v[i] > OUT_MS_MAX ? OUT_MS_MAX : (uint32_t)v[i];
}

bool command_dispatch_output(outputs_t *o, const char *target, const char *method,
                             const char *args_json)
{
    if (o == NULL || target == NULL || method == NULL || outputs_find(o, target) < 0) return false;
    double v[3];
    int n = parse_numbers(args_json, v, 3);
    if (strcmp(method, "pulse") == 0) {
        uint32_t ms = script_ms(v, n, 0);
        if (ms == 0) return true; /* pulse() without a duration: nothing */
        outputs_switch(o, target, OUT_ACT_PULSE, ms, 0, 0, OUT_SRC_SCRIPT);
    } else if (strcmp(method, "on") == 0) {
        outputs_switch(o, target, OUT_ACT_ON, script_ms(v, n, 0), 0, 0, OUT_SRC_SCRIPT);
    } else if (strcmp(method, "off") == 0) {
        outputs_switch(o, target, OUT_ACT_OFF, 0, 0, 0, OUT_SRC_SCRIPT);
    } else if (strcmp(method, "pattern") == 0) {
        uint32_t on_ms = script_ms(v, n, 0), off_ms = script_ms(v, n, 1), ms = script_ms(v, n, 2);
        if (on_ms == 0 || off_ms == 0 || ms == 0) return true;
        outputs_switch(o, target, OUT_ACT_PATTERN, ms, on_ms, off_ms, OUT_SRC_SCRIPT);
    }
    return true;
}
