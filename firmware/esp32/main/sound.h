/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * What a box's sound requests play on the parts it has (decisions BZR-1 to BZR-8): the MAX98357A
 * amplifier and its speaker, an optional passive piezo buzzer (CONFIG_ATALAIA_BUZZER), both or
 * neither. Platform-free: the outputs are callbacks, so the host tests drive it with fakes; the
 * ESP-IDF glue is sound_esp.c.
 *
 * The rule:
 *   - a tone (audio.tone(freq, ms)) plays on every output fitted, together: the buzzer starts,
 *     the speaker plays it (and so sets the time), the buzzer stops;
 *   - a clip (audio.play(clip)) plays its sound file on the speaker when the box has one
 *     (<dir>/<clip>.wav) and the buzzer stays silent; otherwise (no file, or no speaker) its tone
 *     pattern below plays as tones, on every output fitted. A clip without a pattern of its own
 *     gets a short beep. The I/O pod uses the same patterns (PF7).
 */
#ifndef ATALAIA_SOUND_H
#define ATALAIA_SOUND_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SOUND_PATTERN_STEPS 6
#define SOUND_TONE_MAX_HZ   20000u /* a tone above this plays at it */
#define SOUND_TONE_MAX_MS   10000u /* one tone (or rest) is cut to this */
#define SOUND_CLIP_NAME_MAX 32     /* letters, digits, '_' and '-' only */

/* One step of a pattern: hz 0 is a rest. */
typedef struct {
    uint16_t hz;
    uint16_t ms;
} sound_step_t;

typedef struct {
    const char *clip;
    sound_step_t steps[SOUND_PATTERN_STEPS]; /* end at the first step with ms 0 */
} sound_pattern_t;

/* The clip's tone pattern, or the default beep's for an unknown clip (or NULL). Never NULL. */
const sound_pattern_t *sound_pattern(const char *clip);
/* The default beep (any clip without a pattern of its own). */
const sound_pattern_t *sound_default_pattern(void);
/* The steps of a pattern (up to SOUND_PATTERN_STEPS). */
size_t sound_pattern_len(const sound_pattern_t *p);
/* Every named pattern (for the tests and the docs). */
const sound_pattern_t *sound_patterns(size_t *count);

/* "<dir>/<clip>.wav" into out; false when the clip's name is not a safe file name (empty, too
 * long, or anything but letters, digits, '_' and '-') or out is too small. */
bool sound_clip_path(const char *dir, const char *clip, char *out, size_t cap);

/* The outputs. A NULL callback is a part the box does not have. */
typedef struct {
    void *ctx;
    /* The buzzer: starts a tone of hz (0: silent) and returns at once. */
    void (*buzzer)(void *ctx, uint32_t hz);
    /* The speaker: plays a tone of hz for ms and returns when it has played. */
    void (*speaker_tone)(void *ctx, uint32_t hz, uint32_t ms);
    /* The speaker: plays a sound file; non-zero when it has none or cannot play it. */
    int (*speaker_file)(void *ctx, const char *path);
    /* The speaker: stops (flushes) what it plays. */
    void (*speaker_stop)(void *ctx);
    /* Waits ms (a rest, or a tone on the buzzer alone). Required when buzzer is set. */
    void (*wait_ms)(void *ctx, uint32_t ms);
} sound_out_t;

/* Plays a tone of hz for ms on every output (hz 0: a rest of ms; ms 0: nothing). hz is capped at
 * SOUND_TONE_MAX_HZ and ms at SOUND_TONE_MAX_MS. */
void sound_tone(const sound_out_t *out, uint32_t hz, uint32_t ms);
/* Plays a clip: its file on the speaker (from dir; NULL: no files), else its pattern. */
void sound_play(const sound_out_t *out, const char *dir, const char *clip);
/* Silences every output. */
void sound_stop(const sound_out_t *out);

#endif /* ATALAIA_SOUND_H */
