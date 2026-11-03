/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Sound requests onto the speaker and the piezo buzzer (sound.h, decisions BZR-1 to BZR-8).
 */
#include "sound.h"

#include <stdio.h>
#include <string.h>

/*
 * Each clip the modes play (audio.play) as tones, by the kind of moment (BZR-4). The first six
 * are the I/O pod's table of PF7, unchanged; tests check that every clip a mode in modes/ plays
 * has one. Short and distinct; a passive piezo is loudest around 2-4 kHz.
 */
static const sound_pattern_t patterns[] = {
    /* The end of something: a long low boom, or a rising "safe". */
    {"explosion", {{120, 1500}}},
    {"defused", {{1500, 150}, {2000, 250}}},
    /* Warnings: two or three beeps of one pitch. */
    {"armed", {{1000, 150}, {0, 100}, {1000, 150}}},
    {"alarm", {{2500, 300}, {0, 150}, {2500, 300}, {0, 150}, {2500, 300}}},
    {"window", {{2000, 100}, {0, 80}, {2000, 100}}},
    /* Short feedback. */
    {"tick", {{3000, 30}}},
    {"hit", {{2500, 60}}},
    /* Something gained: rising notes. */
    {"captured", {{1200, 150}, {1600, 200}}},
    {"collected", {{1600, 80}, {2000, 120}}},
    {"deposited", {{1200, 100}, {1600, 100}, {2000, 150}}},
    {"healed", {{1000, 120}, {1300, 120}, {1600, 180}}},
};

static const sound_pattern_t default_beep = {"", {{2000, 120}}};

const sound_pattern_t *sound_patterns(size_t *count)
{
    if (count != NULL) *count = sizeof(patterns) / sizeof(patterns[0]);
    return patterns;
}

const sound_pattern_t *sound_default_pattern(void)
{
    return &default_beep;
}

const sound_pattern_t *sound_pattern(const char *clip)
{
    if (clip != NULL) {
        for (size_t i = 0; i < sizeof(patterns) / sizeof(patterns[0]); i++) {
            if (strcmp(clip, patterns[i].clip) == 0) return &patterns[i];
        }
    }
    return &default_beep;
}

size_t sound_pattern_len(const sound_pattern_t *p)
{
    size_t n = 0;
    while (n < SOUND_PATTERN_STEPS && p->steps[n].ms > 0) n++;
    return n;
}

bool sound_clip_path(const char *dir, const char *clip, char *out, size_t cap)
{
    if (dir == NULL || clip == NULL || out == NULL) return false;
    size_t len = strlen(clip);
    if (len == 0 || len > SOUND_CLIP_NAME_MAX) return false;
    for (size_t i = 0; i < len; i++) {
        char c = clip[i];
        bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
                  c == '_' || c == '-';
        if (!ok) return false;
    }
    int n = snprintf(out, cap, "%s/%s.wav", dir, clip);
    return n > 0 && (size_t)n < cap;
}

void sound_tone(const sound_out_t *out, uint32_t hz, uint32_t ms)
{
    if (out == NULL || ms == 0) return;
    if (ms > SOUND_TONE_MAX_MS) ms = SOUND_TONE_MAX_MS;
    if (hz > SOUND_TONE_MAX_HZ) hz = SOUND_TONE_MAX_HZ;
    bool buzzer = out->buzzer != NULL && out->wait_ms != NULL;
    bool speaker = out->speaker_tone != NULL;
    if (!buzzer && !speaker) return; /* nothing to play on: no time spent either */
    if (hz == 0) {
        if (out->wait_ms != NULL) out->wait_ms(out->ctx, ms);
        return;
    }
    if (buzzer) out->buzzer(out->ctx, hz);
    if (speaker) {
        out->speaker_tone(out->ctx, hz, ms); /* the speaker sets the time for both */
    } else {
        out->wait_ms(out->ctx, ms);
    }
    if (buzzer) out->buzzer(out->ctx, 0);
}

void sound_play(const sound_out_t *out, const char *dir, const char *clip)
{
    if (out == NULL) return;
    char path[96];
    if (out->speaker_file != NULL && dir != NULL &&
        sound_clip_path(dir, clip, path, sizeof(path)) && out->speaker_file(out->ctx, path) == 0) {
        return; /* the clip's own sound, on the speaker alone */
    }
    const sound_pattern_t *p = sound_pattern(clip);
    size_t n = sound_pattern_len(p);
    for (size_t i = 0; i < n; i++) sound_tone(out, p->steps[i].hz, p->steps[i].ms);
}

void sound_stop(const sound_out_t *out)
{
    if (out == NULL) return;
    if (out->buzzer != NULL) out->buzzer(out->ctx, 0);
    if (out->speaker_stop != NULL) out->speaker_stop(out->ctx);
}
