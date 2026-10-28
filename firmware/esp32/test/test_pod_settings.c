/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's settings pushed over the radio (main/pod/pod_settings.c): the shared vectors
 * (protocol/vectors/pod_config.json, through pod_config_vectors.h) run in order against one
 * pod that was never configured, through the core's CMD decoder as the pod does; the stored
 * form read back; the limits of the parser; what the settings do to the capabilities.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/msg_codec.h"
#include "check.h"
#include "pod/pod_settings.h"
#include "pod_config_vectors.h"

static int led_brightness = -1;
static int audio_volume = -1;

static int ok_init(void)
{
    return 0;
}
static void led_fill(uint8_t r, uint8_t g, uint8_t b)
{
    (void)r;
    (void)g;
    (void)b;
}
static void led_set(int i, uint8_t r, uint8_t g, uint8_t b)
{
    (void)i;
    (void)r;
    (void)g;
    (void)b;
}
static void led_show(void)
{
}
static void led_set_brightness(uint8_t pct)
{
    led_brightness = pct;
}
static void led_deinit(void)
{
}
static const hal_led_ops_t led_ops = {ok_init,  led_fill,           led_set,
                                      led_show, led_set_brightness, led_deinit};
static void volume(void *ctx, uint8_t v)
{
    (void)ctx;
    audio_volume = v;
}
static void tone(void *ctx, uint32_t hz, uint32_t ms)
{
    (void)ctx;
    (void)hz;
    (void)ms;
}
static void stop(void *ctx)
{
    (void)ctx;
}

static void test_vectors(void)
{
    pod_settings_t s;
    memset(&s, 0, sizeof(s));
    pod_caps_t caps;
    pod_caps_config_t build;
    memset(&build, 0, sizeof(build));
    hal_t hal;
    memset(&hal, 0, sizeof(hal));
    hal.leds = &led_ops;
    build.leds = true;
    build.led_count = 24;
    build.audio = true;
    build.tamper = true;
    pod_audio_t audio = {tone, stop, volume, NULL};
    pod_caps_init(&caps, &build, &hal, &audio);

    for (size_t i = 0; i < POD_VECTOR_COUNT; i++) {
        const pod_vector_t *v = &pod_vectors[i];
        atalaia_cmd_msg_t c;
        CHECK(atalaia_cmd_decode(v->cmd, v->cmd_len, &c));
        CHECK(c.cmd == POD_CMD_POD && c.dest == POD_VECTOR_DEST);
        uint32_t rev = 0;
        pod_config_result_t r = pod_settings_handle(&s, c.params_json, &caps, &build, &rev);
        if ((int)r != v->result)
            fprintf(stderr, "pod vector %s: result %d, want %d\n", v->name, r, v->result);
        CHECK((int)r == v->result);
        char stored[POD_SETTINGS_JSON_MAX];
        CHECK(pod_settings_to_json(&s, stored, sizeof(stored)) > 0 || s.rev == 0);
        if (strcmp(stored, v->stored) != 0) {
            fprintf(stderr, "pod vector %s: stored %s, want %s\n", v->name, stored, v->stored);
        }
        CHECK(strcmp(stored, v->stored) == 0);
        /* The stored form, read back at boot, is the same settings. */
        pod_settings_t back;
        pod_settings_load(&back, stored);
        char again[POD_SETTINGS_JSON_MAX];
        CHECK(pod_settings_to_json(&back, again, sizeof(again)) > 0 && strcmp(again, stored) == 0);
        if (r == POD_CONFIG_APPLIED || r == POD_CONFIG_SAME) CHECK(rev == s.rev);
    }
}

static void test_parser_limits(void)
{
    pod_settings_cmd_t c;
    /* Whitespace, escapes, a repeated key, a trailing comma, trailing bytes, an empty object. */
    CHECK(!pod_settings_parse("{\"v\": 1,\"rev\":1,\"vol\":5}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"rev\":2}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1}x", &c));
    CHECK(!pod_settings_parse("{}", &c));
    CHECK(!pod_settings_parse("", &c));
    CHECK(!pod_settings_parse(NULL, &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":01}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":4294967296}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"btn\":[\"re\\u0064\",\"\",\"\",\"\"]}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"btn\":[\"red\",\"\",\"\",\"\",\"\"]}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"btn\":\"red\"}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"reset\":1}", &c));
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1", &c)); /* cut short */
    CHECK(!pod_settings_parse("{\"v\":1,\"rev\":1,\"vol", &c));
    /* The smallest and the largest valid ones. */
    CHECK(pod_settings_parse("{\"v\":1,\"rev\":1,\"reset\":true}", &c) && c.reset && c.set == 0);
    CHECK(pod_settings_parse("{\"rev\":4294967295,\"v\":1,\"tamper\":true}", &c) &&
          c.rev == 4294967295u && c.tamper && (c.set & POD_SET_TAMPER));
    CHECK(pod_settings_parse("{\"v\":1,\"rev\":2,\"btn\":[\"\",\"\",\"\",\"cyan\"],\"bright\":0}",
                             &c) &&
          strcmp(c.btn[3], "cyan") == 0 && c.bright == 0 && (c.set & POD_SET_BRIGHT));
    /* A damaged stored form gives the empty settings. */
    pod_settings_t s;
    pod_settings_load(&s, "{\"v\":1,\"rev\":3,\"bright\":999}");
    CHECK(s.rev == 0 && s.set == 0);
    pod_settings_load(&s, NULL);
    CHECK(s.rev == 0);
}

static void test_apply(void)
{
    hal_t hal;
    memset(&hal, 0, sizeof(hal));
    hal.leds = &led_ops;
    pod_caps_config_t build;
    memset(&build, 0, sizeof(build));
    build.leds = true;
    build.led_count = 24;
    build.audio = true;
    build.tamper = false; /* a pod built without the enclosure switch */
    build.team[0] = "yellow";
    pod_audio_t audio = {tone, stop, volume, NULL};
    pod_caps_t caps;
    pod_caps_init(&caps, &build, &hal, &audio);
    pod_settings_t s;
    memset(&s, 0, sizeof(s));
    uint32_t rev = 0;
    led_brightness = audio_volume = -1;

    /* A switch that is not fitted is never turned on. */
    CHECK(pod_settings_handle(&s, "{\"v\":1,\"rev\":1,\"tamper\":true}", &caps, &build, &rev) ==
          POD_CONFIG_APPLIED);
    CHECK(!caps.cfg.tamper);
    /* The build's colour stays until one is pushed; an empty one is the game's N-th team. */
    CHECK(caps.cfg.team[0] != NULL && strcmp(caps.cfg.team[0], "yellow") == 0);
    CHECK(pod_settings_handle(&s, "{\"v\":1,\"rev\":2,\"btn\":[\"\",\"white\",\"\",\"\"]}", &caps,
                              &build, &rev) == POD_CONFIG_APPLIED);
    CHECK(caps.cfg.team[0] == NULL && strcmp(caps.cfg.team[1], "white") == 0);
    CHECK(pod_settings_handle(&s, "{\"v\":1,\"rev\":3,\"bright\":25,\"vol\":0}", &caps, &build,
                              &rev) == POD_CONFIG_APPLIED);
    CHECK(led_brightness == 25 && caps.brightness == 25 && audio_volume == 0);
    /* Boot: the stored form applied on a fresh pod gives the same capabilities. */
    char stored[POD_SETTINGS_JSON_MAX];
    CHECK(pod_settings_to_json(&s, stored, sizeof(stored)) > 0);
    pod_settings_t boot;
    pod_settings_load(&boot, stored);
    pod_caps_t caps2;
    pod_caps_init(&caps2, &build, &hal, &audio);
    led_brightness = -1;
    pod_settings_apply(&boot, &caps2, &build);
    CHECK(caps2.cfg.team[0] == NULL && strcmp(caps2.cfg.team[1], "white") == 0 &&
          led_brightness == 25 && boot.rev == 3);
    /* The command's size: the longest one fits the 127 bytes of a CMD's params. */
    char longest[POD_SETTINGS_JSON_MAX];
    snprintf(longest, sizeof(longest),
             "{\"v\":1,\"rev\":4294967295,\"btn\":[\"purple\",\"orange\",\"yellow\",\"purple\"],"
             "\"bright\":100,\"vol\":100,\"tamper\":false}");
    CHECK(strlen(longest) <= 127);
}

void run_pod_settings_tests(void)
{
    test_vectors();
    test_parser_limits();
    test_apply();
}
