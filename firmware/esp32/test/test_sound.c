/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for sound.c: tones and clips on the speaker, the piezo buzzer, both or neither
 * (decisions BZR-1 to BZR-8), with fake outputs that log what they are asked to do.
 */
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "sound.h"

static char log_buf[1024];
static const char *files_present; /* the one file the fake speaker has, or NULL */

static void logf_(const char *s)
{
    size_t len = strlen(log_buf);
    snprintf(log_buf + len, sizeof(log_buf) - len, "%s%s", len ? " " : "", s);
}

static void fake_buzzer(void *ctx, uint32_t hz)
{
    (void)ctx;
    char s[32];
    snprintf(s, sizeof(s), "B%u", (unsigned)hz);
    logf_(s);
}

static void fake_speaker_tone(void *ctx, uint32_t hz, uint32_t ms)
{
    (void)ctx;
    char s[32];
    snprintf(s, sizeof(s), "S%u/%u", (unsigned)hz, (unsigned)ms);
    logf_(s);
}

static int fake_speaker_file(void *ctx, const char *path)
{
    (void)ctx;
    if (files_present == NULL || strcmp(path, files_present) != 0) return -1;
    char s[128];
    snprintf(s, sizeof(s), "F%s", path);
    logf_(s);
    return 0;
}

static void fake_speaker_stop(void *ctx)
{
    (void)ctx;
    logf_("X");
}

static void fake_wait(void *ctx, uint32_t ms)
{
    (void)ctx;
    char s[32];
    snprintf(s, sizeof(s), "W%u", (unsigned)ms);
    logf_(s);
}

static const sound_out_t buzzer_only = {
    .buzzer = fake_buzzer,
    .wait_ms = fake_wait,
};
static const sound_out_t speaker_only = {
    .speaker_tone = fake_speaker_tone,
    .speaker_file = fake_speaker_file,
    .speaker_stop = fake_speaker_stop,
    .wait_ms = fake_wait,
};
static const sound_out_t both = {
    .buzzer = fake_buzzer,
    .speaker_tone = fake_speaker_tone,
    .speaker_file = fake_speaker_file,
    .speaker_stop = fake_speaker_stop,
    .wait_ms = fake_wait,
};
static const sound_out_t neither = {.wait_ms = fake_wait};

static void reset(void)
{
    log_buf[0] = '\0';
    files_present = NULL;
}

static void test_patterns(void)
{
    size_t n = 0;
    const sound_pattern_t *all = sound_patterns(&n);
    CHECK(n >= 11);
    for (size_t i = 0; i < n; i++) {
        size_t len = sound_pattern_len(&all[i]);
        uint32_t total = 0;
        CHECK(len >= 1 && len <= SOUND_PATTERN_STEPS);
        CHECK(all[i].steps[0].hz > 0);       /* starts with a sound */
        CHECK(all[i].steps[len - 1].hz > 0); /* and ends with one */
        for (size_t s = 0; s < len; s++) total += all[i].steps[s].ms;
        CHECK(total <= 2000); /* never holds the task long */
        CHECK(sound_pattern(all[i].clip) == &all[i]);
        for (size_t j = 0; j < i; j++) CHECK(strcmp(all[i].clip, all[j].clip) != 0);
    }
    /* The I/O pod's table of PF7, unchanged. */
    const sound_pattern_t *armed = sound_pattern("armed");
    CHECK(sound_pattern_len(armed) == 3 && armed->steps[0].hz == 1000 && armed->steps[1].hz == 0);
    CHECK(sound_pattern("explosion")->steps[0].hz == 120 &&
          sound_pattern("explosion")->steps[0].ms == 1500);
    /* Unknown, empty and NULL: the default beep. */
    CHECK(sound_pattern("no_such_clip") == sound_default_pattern());
    CHECK(sound_pattern("") == sound_default_pattern());
    CHECK(sound_pattern(NULL) == sound_default_pattern());
    CHECK(sound_pattern_len(sound_default_pattern()) == 1);
    CHECK(sound_default_pattern()->steps[0].hz == 2000);
}

/* Every clip a mode in modes/ plays has a pattern of its own, not the default beep. */
static void test_mode_clips_have_patterns(void)
{
#ifdef MODES_DIR
    DIR *d = opendir(MODES_DIR);
    CHECK(d != NULL);
    if (d == NULL) return;
    int found = 0;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        if (e->d_name[0] == '.') continue;
        char path[512];
        snprintf(path, sizeof(path), "%s/%s/node.lua", MODES_DIR, e->d_name);
        FILE *f = fopen(path, "rb");
        if (f == NULL) continue;
        char *src = malloc(256 * 1024);
        size_t len = src ? fread(src, 1, 256 * 1024 - 1, f) : 0;
        fclose(f);
        if (src == NULL) continue;
        src[len] = '\0';
        const char *needle = "audio.play(\"";
        for (char *p = strstr(src, needle); p != NULL; p = strstr(p + 1, needle)) {
            char clip[64];
            const char *start = p + strlen(needle);
            const char *end = strchr(start, '"');
            if (end == NULL || (size_t)(end - start) >= sizeof(clip)) continue;
            memcpy(clip, start, (size_t)(end - start));
            clip[end - start] = '\0';
            found++;
            if (sound_pattern(clip) == sound_default_pattern()) {
                fprintf(stderr, "sound: %s plays \"%s\", which has no tone pattern\n", path, clip);
            }
            CHECK(sound_pattern(clip) != sound_default_pattern());
        }
        free(src);
    }
    closedir(d);
    CHECK(found >= 20); /* the scan found the modes' clips */
#endif
}

static void test_clip_path(void)
{
    char out[64];
    CHECK(sound_clip_path("/littlefs/audio", "armed", out, sizeof(out)) &&
          strcmp(out, "/littlefs/audio/armed.wav") == 0);
    CHECK(sound_clip_path("/a", "Big_one-2", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "../etc/x", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "a/b", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "a.wav", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "a b", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", "abcdefghijabcdefghijabcdefghijabc", out, sizeof(out))); /* 33 */
    CHECK(sound_clip_path("/a", "abcdefghijabcdefghijabcdefghijab", out, sizeof(out)));   /* 32 */
    CHECK(!sound_clip_path("/a", "armed", out, 8)); /* too small */
    CHECK(!sound_clip_path(NULL, "armed", out, sizeof(out)));
    CHECK(!sound_clip_path("/a", NULL, out, sizeof(out)));
}

static void test_tone_routing(void)
{
    reset();
    sound_tone(&buzzer_only, 1500, 200);
    CHECK(strcmp(log_buf, "B1500 W200 B0") == 0);

    reset();
    sound_tone(&speaker_only, 1500, 200);
    CHECK(strcmp(log_buf, "S1500/200") == 0);

    reset();
    sound_tone(&both, 1500, 200); /* together: the speaker sets the time */
    CHECK(strcmp(log_buf, "B1500 S1500/200 B0") == 0);

    reset();
    sound_tone(&neither, 1500, 200); /* nothing fitted: no time spent */
    CHECK(log_buf[0] == '\0');

    reset();
    sound_tone(&both, 0, 100); /* a rest */
    CHECK(strcmp(log_buf, "W100") == 0);

    reset();
    sound_tone(&both, 1500, 0); /* no length: nothing */
    CHECK(log_buf[0] == '\0');

    reset();
    sound_tone(&both, 30000, 60000); /* capped */
    CHECK(strcmp(log_buf, "B20000 S20000/10000 B0") == 0);

    reset();
    sound_out_t no_wait = buzzer_only;
    no_wait.wait_ms = NULL; /* a buzzer without a clock cannot be timed: not used */
    sound_tone(&no_wait, 1500, 200);
    CHECK(log_buf[0] == '\0');

    sound_tone(NULL, 1500, 200); /* no crash */
}

static void test_clip_routing(void)
{
    /* The buzzer alone: the pattern as tones. */
    reset();
    sound_play(&buzzer_only, "/littlefs/audio", "armed");
    CHECK(strcmp(log_buf, "B1000 W150 B0 W100 B1000 W150 B0") == 0);

    /* The speaker alone, no file: the pattern on the speaker (it was silent before, BZR-5). */
    reset();
    sound_play(&speaker_only, "/littlefs/audio", "captured");
    CHECK(strcmp(log_buf, "S1200/150 S1600/200") == 0);

    /* The speaker with the clip's file: the file. */
    reset();
    files_present = "/littlefs/audio/captured.wav";
    sound_play(&speaker_only, "/littlefs/audio", "captured");
    CHECK(strcmp(log_buf, "F/littlefs/audio/captured.wav") == 0);

    /* Both, with the file: the file on the speaker, the buzzer silent. */
    reset();
    files_present = "/littlefs/audio/defused.wav";
    sound_play(&both, "/littlefs/audio", "defused");
    CHECK(strcmp(log_buf, "F/littlefs/audio/defused.wav") == 0);

    /* Both, no file: the pattern on both together. */
    reset();
    sound_play(&both, "/littlefs/audio", "defused");
    CHECK(strcmp(log_buf, "B1500 S1500/150 B0 B2000 S2000/250 B0") == 0);

    /* No file directory: the pattern. */
    reset();
    files_present = "/littlefs/audio/tick.wav";
    sound_play(&both, NULL, "tick");
    CHECK(strcmp(log_buf, "B3000 S3000/30 B0") == 0);

    /* An unknown clip: the default beep. A name that is not a safe file name never reaches the
     * file system. */
    reset();
    sound_play(&buzzer_only, "/littlefs/audio", "fanfare");
    CHECK(strcmp(log_buf, "B2000 W120 B0") == 0);
    reset();
    files_present = "/littlefs/audio/../x.wav";
    sound_play(&both, "/littlefs/audio", "../x");
    CHECK(strcmp(log_buf, "B2000 S2000/120 B0") == 0);

    /* Nothing fitted. */
    reset();
    sound_play(&neither, "/littlefs/audio", "alarm");
    CHECK(log_buf[0] == '\0');
    sound_play(NULL, "/littlefs/audio", "alarm"); /* no crash */
}

static void test_stop(void)
{
    reset();
    sound_stop(&both);
    CHECK(strcmp(log_buf, "B0 X") == 0);
    reset();
    sound_stop(&buzzer_only);
    CHECK(strcmp(log_buf, "B0") == 0);
    reset();
    sound_stop(&neither);
    CHECK(log_buf[0] == '\0');
    sound_stop(NULL);
}

void run_sound_tests(void)
{
    test_patterns();
    test_mode_clips_have_patterns();
    test_clip_path();
    test_tone_routing();
    test_clip_routing();
    test_stop();
}
