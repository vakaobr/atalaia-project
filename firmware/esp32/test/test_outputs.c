/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the box's output layer (outputs.c, outputs_admin.c, command_dispatch_output; draft
 * RFC "The expansion port", increment 2): with a fake back-end, events and settings store. The
 * admin's settings (disabled until enabled at the box), the limits (max on, the 500 ms floor of a
 * simple output, patterns, a script's 2 starts a second), the game-state rules (only while a game
 * runs; off at pause, halt and end; the end's 10 s grace; the admin's test only between games),
 * output.switched and node.modules, CMD 12's params against the shared vectors
 * (protocol/vectors/cmd.json, "output_params"), and a mode's cap() calls through the node runner
 * with the real core.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "hal/stub/hal_stub.h"
#include "node_runner.h"
#include "outputs.h"
#include "outputs_admin.h"
#include "preset_store.h"

#ifndef CMD_VECTORS_JSON
#define CMD_VECTORS_JSON "protocol/vectors/cmd.json"
#endif

/* ---- Fakes -------------------------------------------------------------------------- */

typedef struct {
    bool on, live;
    int drives;
} fake_be_t;

static fake_be_t be[OUTPUTS_MAX];
static char events[2048];
static int event_count;
static int saves;
static out_settings_t saved[OUTPUTS_MAX];

static void fake_drive(void *ctx, bool on, bool live, uint32_t now_ms)
{
    (void)now_ms;
    fake_be_t *b = (fake_be_t *)ctx;
    b->on = on;
    b->live = live;
    b->drives++;
}

static void fake_event(void *ctx, const char *type, const char *data_json)
{
    (void)ctx;
    size_t len = strlen(events);
    snprintf(events + len, sizeof(events) - len, "%s %s\n", type, data_json);
    event_count++;
}

static bool fake_save(void *ctx, int index, const out_settings_t *s)
{
    (void)ctx;
    saves++;
    if (index >= 0 && index < OUTPUTS_MAX) saved[index] = *s;
    return true;
}

static outputs_t o;
static uint32_t now;

/* Outputs with n simple outputs (GPIO 46, then 45), enabled with these functions (NULL: as a new
 * box has them, disabled). */
static void fresh(int n, const char *fn1, const char *fn2)
{
    memset(be, 0, sizeof(be));
    events[0] = '\0';
    event_count = 0;
    saves = 0;
    outputs_ops_t ops = {.event = fake_event, .save = fake_save, .ctx = NULL};
    outputs_init(&o, &ops);
    const char *fns[2] = {fn1, fn2};
    for (int i = 0; i < n; i++) {
        out_backend_t b = {.ctx = &be[i], .drive = fake_drive};
        out_settings_t s;
        outputs_default_settings(i, &s);
        if (fns[i] != NULL) {
            s.enabled = true;
            snprintf(s.function, sizeof(s.function), "%s", fns[i]);
        }
        CHECK(outputs_add_simple(&o, i == 0 ? 46 : 45, &b, &s) == i);
    }
    now = 10000;
    outputs_tick(&o, OUT_GAME_NONE, now);
}

static void run(out_game_t g, uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 10) {
        now += 10;
        outputs_tick(&o, g, now);
    }
}

/* ---- Settings ------------------------------------------------------------------------- */

static void test_defaults_and_settings(void)
{
    fresh(2, NULL, NULL);
    CHECK(o.count == 2);
    CHECK(strcmp(o.ch[0].id, "out.1") == 0 && strcmp(o.ch[1].id, "out.2") == 0);
    CHECK(!o.ch[0].set.enabled && o.ch[0].set.max_on_s == OUT_MAX_ON_DEFAULT_S);
    CHECK(outputs_enabled_count(&o) == 0);
    /* Disabled until the admin enables it at the box (EXP-28): never on, even in a game. */
    run(OUT_GAME_RUNNING, 20);
    CHECK(outputs_switch(&o, "out.1", OUT_ACT_PULSE, 1000, 0, 0, OUT_SRC_FIELD) == OUT_DISABLED);
    CHECK(!outputs_level(&o, 0) && !be[0].live); /* a disabled channel sends no live "off" */
    /* Settings only between games. */
    out_settings_t s = o.ch[0].set;
    s.enabled = true;
    CHECK(outputs_configure(&o, 0, &s) == OUT_BUSY);
    run(OUT_GAME_NONE, 20);
    snprintf(s.function, sizeof(s.function), "siren");
    CHECK(outputs_configure(&o, 0, &s) == OUT_OK);
    CHECK(saves == 1 && saved[0].enabled && strcmp(saved[0].function, "siren") == 0);
    CHECK(strcmp(o.ch[0].id, "siren") == 0 && outputs_find(&o, "siren") == 0);
    /* The same function on the second: siren.2. */
    s = o.ch[1].set;
    snprintf(s.function, sizeof(s.function), "siren");
    CHECK(outputs_configure(&o, 1, &s) == OUT_OK);
    CHECK(strcmp(o.ch[1].id, "siren.2") == 0);
    /* Out of range. */
    s.max_on_s = 0;
    CHECK(outputs_configure(&o, 1, &s) == OUT_BAD_ARGS);
    s.max_on_s = 601;
    CHECK(outputs_configure(&o, 1, &s) == OUT_BAD_ARGS);
    s.max_on_s = 30;
    snprintf(s.function, sizeof(s.function), "Siren");
    CHECK(outputs_configure(&o, 1, &s) == OUT_BAD_ARGS);
    CHECK(outputs_configure(&o, 2, &s) == OUT_NO_SUCH);
    CHECK(outputs_function_ok("out.9") && !outputs_function_ok("out.10") &&
          !outputs_function_ok("bomb") && outputs_function_ok("horn"));
    /* Stored settings that make no sense are the defaults. */
    outputs_t o2;
    outputs_init(&o2, NULL);
    out_settings_t bad = {.enabled = true, .function = "laser", .max_on_s = 30};
    out_backend_t b = {0};
    CHECK(outputs_add_simple(&o2, 46, &b, &bad) == 0);
    CHECK(!o2.ch[0].set.enabled && strcmp(o2.ch[0].id, "out.1") == 0);
    CHECK(outputs_add_simple(&o2, 45, &b, NULL) == 1);
    CHECK(outputs_add_simple(&o2, 5, &b, NULL) == -1); /* OUTPUTS_MAX */
}

static void test_modules_text(void)
{
    fresh(2, "siren", NULL);
    char text[OUT_MODULES_MAX + 1];
    CHECK(outputs_modules_text(&o, text, sizeof(text)) == strlen("g46:servo:siren"));
    CHECK(strcmp(text, "g46:servo:siren") == 0);
    fresh(2, "smoke", "smoke");
    outputs_modules_text(&o, text, sizeof(text));
    CHECK(strcmp(text, "g46:servo:smoke;g45:servo:smoke.2") == 0);
    CHECK(outputs_enabled_count(&o) == 2);
    fresh(1, NULL, NULL);
    CHECK(outputs_modules_text(&o, text, sizeof(text)) == 0 && text[0] == '\0');
}

/* node.outputs_disabled's text (EXPL-13): the outputs fitted but not enabled, in node.modules'
 * form; never past OUT_MODULES_MAX or the buffer. */
static void test_disabled_text(void)
{
    char text[OUT_MODULES_MAX + 1];
    fresh(2, "siren", "smoke");
    CHECK(outputs_disabled_text(&o, text, sizeof(text)) == 0 && text[0] == '\0');
    fresh(1, NULL, NULL);
    CHECK(outputs_disabled_text(&o, text, sizeof(text)) == strlen("g46:servo:out.1"));
    CHECK(strcmp(text, "g46:servo:out.1") == 0);
    /* The admin set a function and left it disabled; the other is enabled. */
    fresh(2, "siren", NULL);
    out_settings_t s = o.ch[1].set;
    snprintf(s.function, sizeof(s.function), "%s", "horn");
    CHECK(outputs_configure(&o, 1, &s) == OUT_OK);
    CHECK(outputs_disabled_text(&o, text, sizeof(text)) == strlen("g45:servo:horn"));
    CHECK(strcmp(text, "g45:servo:horn") == 0);
    outputs_modules_text(&o, text, sizeof(text));
    CHECK(strcmp(text, "g46:servo:siren") == 0);
    /* Both disabled with the same function: the second's id is horn.2. */
    s = o.ch[0].set;
    s.enabled = false;
    snprintf(s.function, sizeof(s.function), "%s", "horn");
    CHECK(outputs_configure(&o, 0, &s) == OUT_OK);
    outputs_disabled_text(&o, text, sizeof(text));
    CHECK(strcmp(text, "g46:servo:horn;g45:servo:horn.2") == 0);
    /* A short buffer: whole entries only. */
    char small[20];
    CHECK(outputs_disabled_text(&o, small, sizeof(small)) == strlen("g46:servo:horn"));
    CHECK(strcmp(small, "g46:servo:horn") == 0);
    CHECK(outputs_disabled_text(&o, small, 0) == 0);
}

/* ---- Switching -------------------------------------------------------------------------- */

static void test_only_while_a_game_runs(void)
{
    fresh(1, "siren", NULL);
    CHECK(!be[0].live && !be[0].on);
    CHECK(outputs_switch(&o, "siren", OUT_ACT_PULSE, 2000, 0, 0, OUT_SRC_FIELD) == OUT_NOT_NOW);
    run(OUT_GAME_RUNNING, 20);
    CHECK(be[0].live && !be[0].on); /* a live "off" while the game runs */
    CHECK(outputs_switch(&o, "siren", OUT_ACT_PULSE, 2000, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    CHECK(strstr(events,
                 "output.switched {\"capability\":\"siren\",\"ms\":2000,\"source\":\"field\"}") !=
          NULL);
    run(OUT_GAME_RUNNING, 10);
    CHECK(be[0].on && be[0].live);
    run(OUT_GAME_RUNNING, 1980);
    CHECK(be[0].on);
    run(OUT_GAME_RUNNING, 20);
    CHECK(!be[0].on && be[0].live); /* its time is up: off, and no output.switched for that */
    CHECK(event_count == 1);
    /* A capability the box does not have does nothing. */
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, 2000, 0, 0, OUT_SRC_SCRIPT) == OUT_NO_SUCH);
}

static void test_limits(void)
{
    fresh(1, "smoke", NULL);
    out_settings_t s = o.ch[0].set;
    s.max_on_s = 5;
    CHECK(outputs_configure(&o, 0, &s) == OUT_OK);
    run(OUT_GAME_RUNNING, 20);
    /* on() without a time: its max on; a longer call is cut to it. */
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_ON, 0, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
    CHECK(strstr(events, "\"ms\":5000,\"source\":\"script\"") != NULL);
    run(OUT_GAME_RUNNING, 5000);
    CHECK(!be[0].on);
    run(OUT_GAME_RUNNING, 600);
    events[0] = '\0';
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, 60000, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    CHECK(strstr(events, "\"ms\":5000") != NULL);
    /* Off before its time: said, with who. */
    events[0] = '\0';
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_OFF, 0, 0, 0, OUT_SRC_GM) == OUT_OK);
    CHECK(strcmp(events,
                 "output.switched {\"capability\":\"smoke\",\"ms\":0,\"source\":\"gm\"}\n") == 0);
    run(OUT_GAME_RUNNING, 10);
    CHECK(!be[0].on);
    /* An off of an output that is off says nothing. */
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_OFF, 0, 0, 0, OUT_SRC_GM) == OUT_OK);
    CHECK(strstr(events + 10, "output.switched") == NULL);
    /* On again within 500 ms of the last change: refused; after it: fine (EXP-30). */
    run(OUT_GAME_RUNNING, 400);
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, 1000, 0, 0, OUT_SRC_FIELD) == OUT_TOO_SOON);
    run(OUT_GAME_RUNNING, 100);
    events[0] = '\0';
    /* A pulse shorter than a switch can show runs for 500 ms. */
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, 100, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    CHECK(strstr(events, "\"ms\":500,") != NULL);
    run(OUT_GAME_RUNNING, 490);
    CHECK(be[0].on);
    run(OUT_GAME_RUNNING, 20);
    CHECK(!be[0].on);
    /* Out of range for a field call. */
    run(OUT_GAME_RUNNING, 600);
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, 0, 0, 0, OUT_SRC_FIELD) == OUT_BAD_ARGS);
    CHECK(outputs_switch(&o, "smoke", OUT_ACT_PULSE, OUT_MS_MAX + 1, 0, 0, OUT_SRC_FIELD) ==
          OUT_BAD_ARGS);
    CHECK(outputs_switch(&o, "*", OUT_ACT_ON, 1000, 0, 0, OUT_SRC_GM) == OUT_BAD_ARGS);
}

static void test_patterns(void)
{
    fresh(1, "strobe", NULL);
    run(OUT_GAME_RUNNING, 20);
    /* A simple output's pattern: on and off at least 500 ms (EXP-36). */
    CHECK(outputs_switch(&o, "strobe", OUT_ACT_PATTERN, 5000, 400, 500, OUT_SRC_FIELD) ==
          OUT_BAD_ARGS);
    CHECK(outputs_switch(&o, "strobe", OUT_ACT_PATTERN, 5000, 500, 10001, OUT_SRC_FIELD) ==
          OUT_BAD_ARGS);
    CHECK(outputs_switch(&o, "strobe", OUT_ACT_PATTERN, 5000, 500, 1000, OUT_SRC_FIELD) == OUT_OK);
    CHECK(strstr(events, "\"ms\":5000") != NULL);
    int changes = 0;
    bool last = true;
    for (int t = 0; t < 6000; t += 10) {
        run(OUT_GAME_RUNNING, 10);
        if (be[0].on != last) changes++;
        last = be[0].on;
        /* 500 on, 1000 off: on in [0, 500), [1500, 2000), [3000, 3500), [4500, 5000). */
        int phase = (t + 10) % 1500;
        if (t + 10 < 5000) CHECK(be[0].on == (phase < 500));
    }
    CHECK(!be[0].on);
    CHECK(changes == 7); /* on-off four times, the last off at the end */
}

static void test_game_state_rules(void)
{
    fresh(2, "siren", "horn");
    run(OUT_GAME_RUNNING, 20);
    CHECK(outputs_switch(&o, "siren", OUT_ACT_ON, 0, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    run(OUT_GAME_RUNNING, 20);
    CHECK(be[0].on);
    int before = event_count;
    /* Pause: off, no event (the game's own state says why), and not on again on resume. */
    run(OUT_GAME_PAUSED, 20);
    CHECK(!be[0].on && !be[0].live);
    CHECK(event_count == before);
    CHECK(outputs_switch(&o, "siren", OUT_ACT_PULSE, 1000, 0, 0, OUT_SRC_GM) == OUT_NOT_NOW);
    run(OUT_GAME_RUNNING, 20);
    CHECK(!be[0].on && be[0].live);
    /* A script halted by the sandbox: off. */
    run(OUT_GAME_RUNNING, 600);
    CHECK(outputs_switch(&o, "horn", OUT_ACT_ON, 0, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
    run(OUT_GAME_HALTED, 20);
    CHECK(!be[1].on && !be[1].live);
    CHECK(outputs_switch(&o, "horn", OUT_ACT_ON, 0, 0, 0, OUT_SRC_SCRIPT) == OUT_NOT_NOW);
    /* The end: off, then a 10 s grace for an end-of-game horn, cut at its end (EXP-29). */
    run(OUT_GAME_RUNNING, 600);
    CHECK(outputs_switch(&o, "siren", OUT_ACT_ON, 0, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    run(OUT_GAME_RUNNING, 20);
    outputs_game_end(&o, now);
    CHECK(o.grace && o.game == OUT_GAME_ENDED);
    run(OUT_GAME_ENDED, 10);
    CHECK(!be[0].on && !be[0].live);
    events[0] = '\0';
    CHECK(outputs_switch(&o, "horn", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
    run(OUT_GAME_ENDED, 20);
    CHECK(be[1].on && be[1].live);
    /* The box leaves the game during the grace: the grace goes on. */
    run(OUT_GAME_NONE, 5000);
    CHECK(!be[1].on && !be[1].live);
    CHECK(outputs_switch(&o, "horn", OUT_ACT_PULSE, 8000, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    CHECK(strstr(events, "\"ms\":4970,\"source\":\"field\"") != NULL); /* cut at the grace's end */
    run(OUT_GAME_NONE, 4990);
    CHECK(!be[1].on);
    CHECK(outputs_switch(&o, "horn", OUT_ACT_PULSE, 1000, 0, 0, OUT_SRC_FIELD) == OUT_NOT_NOW);
    CHECK(!o.grace);
    /* The end with nothing running before (a box that rebooted into an ended game): just off. */
    fresh(1, "siren", NULL);
    outputs_game_end(&o, now);
    CHECK(!o.grace);
}

static void test_admin_test(void)
{
    fresh(2, "siren", NULL);
    /* Between games only, enabled only, 1 s, said as box_admin. */
    CHECK(outputs_test(&o, 1) == OUT_DISABLED);
    CHECK(outputs_test(&o, 0) == OUT_OK);
    CHECK(strstr(events, "\"ms\":1000,\"source\":\"box_admin\"") != NULL);
    run(OUT_GAME_NONE, 20);
    CHECK(be[0].on && be[0].live);
    run(OUT_GAME_NONE, 1000);
    CHECK(!be[0].on && !be[0].live);
    run(OUT_GAME_RUNNING, 600);
    CHECK(outputs_test(&o, 0) == OUT_NOT_NOW);
    CHECK(outputs_test(&o, 5) == OUT_NO_SUCH);
}

static void test_script_rate(void)
{
    fresh(1, "light", NULL);
    run(OUT_GAME_RUNNING, 20);
    /* Re-triggers while on change nothing on the pin, so only the rate limit applies. */
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
    run(OUT_GAME_RUNNING, 100);
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
    run(OUT_GAME_RUNNING, 100);
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_RATE);
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_RATE);
    CHECK(strstr(events, "script.error {\"message\":\"output light: more than 2 starts a second, "
                         "dropped\"}") != NULL);
    int errors = 0;
    for (const char *p = events; (p = strstr(p, "script.error")) != NULL; p++) errors++;
    CHECK(errors == 1); /* once a game */
    /* The field is not a script: not limited this way. */
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    /* A second later the script may again. */
    run(OUT_GAME_RUNNING, 1000);
    CHECK(outputs_switch(&o, "light", OUT_ACT_PULSE, 3000, 0, 0, OUT_SRC_SCRIPT) == OUT_OK);
}

/* ---- CMD 12 ------------------------------------------------------------------------------ */

static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    if (buf != NULL && fread(buf, 1, (size_t)n, f) != (size_t)n) {
        free(buf);
        buf = NULL;
    }
    if (buf != NULL) buf[n] = '\0';
    fclose(f);
    return buf;
}

/* The object that starts at p ('{'), copied into out (compact enough for screen_json). */
static const char *copy_object(const char *p, char *out, size_t cap)
{
    int depth = 0;
    size_t n = 0;
    bool in_str = false;
    for (; *p; p++) {
        char c = *p;
        if (n + 1 < cap) out[n++] = c;
        if (in_str) {
            if (c == '\\' && p[1]) {
                if (n + 1 < cap) out[n++] = *++p;
            } else if (c == '"') {
                in_str = false;
            }
            continue;
        }
        if (c == '"') in_str = true;
        if (c == '{') depth++;
        if (c == '}' && --depth == 0) {
            out[n] = '\0';
            return p + 1;
        }
    }
    out[n] = '\0';
    return p;
}

static void test_cmd_vectors(void)
{
    char *json = slurp(CMD_VECTORS_JSON);
    CHECK(json != NULL);
    if (json == NULL) return;
    const char *section = strstr(json, "\"output_params\"");
    CHECK(section != NULL);
    const char *refused = section ? strstr(section, "\"refused\"") : NULL;
    CHECK(refused != NULL);
    int valid_n = 0, refused_n = 0;
    for (const char *p = section; p != NULL && (p = strstr(p, "\"params\":")) != NULL;) {
        bool is_refused = refused != NULL && p > refused;
        const char *obj = strchr(p, '{');
        char params[256];
        p = copy_object(obj, params, sizeof(params));
        const char *problem = outputs_cmd_problem(params);
        if (!is_refused) {
            valid_n++;
            if (problem != NULL) fprintf(stderr, "cmd.json valid %s: %s\n", params, problem);
            CHECK(problem == NULL);
        } else {
            refused_n++;
            /* The reason follows the params: the box gives the same words. */
            const char *r = strstr(p, "\"reason\": \"");
            char reason[96] = "";
            if (r != NULL) sscanf(r + 11, "%95[^\"]", reason);
            if (problem == NULL || strcmp(problem, reason) != 0) {
                fprintf(stderr, "cmd.json refused %s: box %s, vector %s\n", params,
                        problem ? problem : "(taken)", reason);
            }
            CHECK(problem != NULL && strcmp(problem, reason) == 0);
        }
    }
    CHECK(valid_n == 9 && refused_n == 14);
    free(json);

    /* The channel's own floors come after (protocol/expansion-port.md, section 8). */
    fresh(2, "siren", "strobe");
    run(OUT_GAME_RUNNING, 20);
    const char *why = "x";
    CHECK(outputs_cmd(&o,
                      "{\"capability\":\"siren\",\"act\":\"pulse\",\"ms\":10000,\"src\":\"field\"}",
                      &why) == OUT_OK &&
          why == NULL);
    CHECK(strstr(events, "\"capability\":\"siren\",\"ms\":10000,\"source\":\"field\"") != NULL);
    /* pattern_shortest: valid params, but 10 ms is below a simple output's 500. */
    CHECK(outputs_cmd(&o,
                      "{\"capability\":\"strobe\",\"act\":\"pattern\",\"ms\":1,\"on_ms\":10,"
                      "\"off_ms\":10000,\"src\":\"gm\"}",
                      NULL) == OUT_BAD_ARGS);
    CHECK(outputs_cmd(&o,
                      "{\"capability\":\"strobe\",\"act\":\"pattern\",\"ms\":20000,"
                      "\"on_ms\":500,\"off_ms\":500,\"src\":\"field\"}",
                      NULL) == OUT_OK);
    CHECK(outputs_cmd(&o, "{\"capability\":\"smoke\",\"act\":\"off\",\"src\":\"gm\"}", NULL) ==
          OUT_NO_SUCH);
    CHECK(outputs_cmd(&o, "{\"capability\":\"siren\",\"act\":\"on\",\"src\":\"field\"}", &why) ==
              OUT_BAD_ARGS &&
          why != NULL);
    run(OUT_GAME_RUNNING, 20);
    CHECK(be[0].on && be[1].on);
    /* Every output off, by the GM. */
    events[0] = '\0';
    CHECK(outputs_cmd(&o, "{\"capability\":\"*\",\"act\":\"off\",\"src\":\"gm\"}", NULL) == OUT_OK);
    CHECK(strstr(events, "\"capability\":\"siren\",\"ms\":0,\"source\":\"gm\"") != NULL);
    CHECK(strstr(events, "\"capability\":\"strobe\",\"ms\":0,\"source\":\"gm\"") != NULL);
    run(OUT_GAME_RUNNING, 10);
    CHECK(!be[0].on && !be[1].on);
}

/* ---- The admin at the box ------------------------------------------------------------------ */

static void test_admin_screen(void)
{
    fresh(2, NULL, NULL);
    outputs_admin_t a;
    outputs_admin_open(&a, &o);
    CHECK(outputs_admin_active(&a));
    screen_update_t su;
    CHECK(outputs_admin_screen(&a, &su) && strcmp(su.template_name, "start_confirm") == 0);
    CHECK(strstr(su.data_json, "\"output\":1,\"of\":2,\"gpio\":46,\"fn\":\"out.1\"") != NULL);
    CHECK(strstr(su.data_json, "\"enabled\":false") != NULL);
    CHECK(outputs_admin_key(&a, '1')); /* enabled */
    CHECK(o.ch[0].set.enabled && saves == 1);
    CHECK(outputs_admin_key(&a, '2')); /* out.1 -> siren */
    CHECK(strcmp(o.ch[0].set.function, "siren") == 0);
    for (int i = 0; i < 4; i++) outputs_admin_key(&a, '2'); /* strobe, smoke, light, horn */
    CHECK(strcmp(o.ch[0].set.function, "horn") == 0);
    outputs_admin_key(&a, '2'); /* back to out.1 */
    CHECK(strcmp(o.ch[0].set.function, "out.1") == 0);
    outputs_admin_key(&a, '2');
    CHECK(outputs_admin_key(&a, '3')); /* 30 -> 60 s */
    CHECK(o.ch[0].set.max_on_s == 60);
    CHECK(outputs_admin_next_max(600) == 5 && outputs_admin_next_max(5) == 10);
    CHECK(outputs_admin_key(&a, '5')); /* the 1 s test */
    CHECK(a.testing && o.ch[0].level);
    outputs_admin_screen(&a, &su);
    CHECK(strstr(su.data_json, "\"fn\":\"siren\",\"enabled\":true,\"max_s\":60,\"testing\":true"));
    CHECK(outputs_admin_key(&a, '0')); /* the next output */
    CHECK(a.index == 1 && !a.testing);
    CHECK(!outputs_admin_key(&a, '#'));
    CHECK(!outputs_admin_active(&a) && !outputs_admin_screen(&a, &su));
    /* No outputs: nothing to open. */
    outputs_t none;
    outputs_init(&none, NULL);
    outputs_admin_open(&a, &none);
    CHECK(!outputs_admin_active(&a));
}

static void test_admin_console(void)
{
    fresh(1, NULL, NULL);
    char reply[240];
    CHECK(outputs_admin_args("output 1 enable") == 2);
    CHECK(outputs_admin_args("output 1 test") == 2);
    CHECK(outputs_admin_args("output 1 function siren") == 3);
    CHECK(outputs_admin_args("output 1 max 30") == 3);
    CHECK(outputs_admin_args("outputs") == -1 && outputs_admin_args("join x") == -1);
    CHECK(!outputs_admin_command(&o, "join x", false, reply, sizeof(reply)));
    CHECK(outputs_admin_command(&o, "outputs", false, reply, sizeof(reply)));
    CHECK(strstr(reply, "output 1 GPIO 46: out.1, disabled, at most 30 s, off") != NULL);
    CHECK(outputs_admin_command(&o, "output 1 enable", true, reply, sizeof(reply)));
    CHECK(strstr(reply, "not during a game") != NULL && !o.ch[0].set.enabled);
    CHECK(outputs_admin_command(&o, "output 1 enable", false, reply, sizeof(reply)));
    CHECK(o.ch[0].set.enabled);
    CHECK(outputs_admin_command(&o, "output 1 function smoke", false, reply, sizeof(reply)));
    CHECK(strstr(reply, "output 1 GPIO 46: smoke, enabled") != NULL);
    CHECK(outputs_admin_command(&o, "output 1 function bomb", false, reply, sizeof(reply)));
    CHECK(strcmp(o.ch[0].set.function, "smoke") == 0);
    CHECK(outputs_admin_command(&o, "output 1 max 120", false, reply, sizeof(reply)));
    CHECK(o.ch[0].set.max_on_s == 120);
    CHECK(outputs_admin_command(&o, "output 1 max 0", false, reply, sizeof(reply)));
    CHECK(o.ch[0].set.max_on_s == 120);
    CHECK(outputs_admin_command(&o, "output 1 test", false, reply, sizeof(reply)));
    CHECK(o.ch[0].level && strstr(reply, ", on") != NULL);
    CHECK(outputs_admin_command(&o, "output 2 enable", false, reply, sizeof(reply)));
    CHECK(strstr(reply, "@output <1-1>") != NULL);
    CHECK(outputs_admin_command(&o, "output 1 disable", false, reply, sizeof(reply)));
    CHECK(!o.ch[0].set.enabled);
    run(OUT_GAME_NONE, 10);
    CHECK(!be[0].on); /* a disabled output goes off at once */
}

/* ---- A mode's cap() calls through the node runner and the core --------------------------- */

static const char outputs_mode[] =
    "on('game.start', function() cap('siren'):on() end)\n"
    "on('team_input.hold', function(e)\n"
    "  cap('siren'):off()\n"
    "  cap('smoke'):pulse(1000)\n" /* this box has no smoke: nothing */
    "  cap('horn'):pattern(500, 500, 2000)\n"
    "end)\n"
    "on('game.end', function() cap('horn'):pulse(3000) end)\n";

static void test_mode_calls(void)
{
    fresh(2, "siren", "horn");
    static hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t r;
    node_runner_init(&r, &hal, 0);
    r.outputs = &o;
    static preset_t p;
    memset(&p, 0, sizeof(p));
    snprintf(p.mode_id, sizeof(p.mode_id), "org.example.outputs");
    memcpy(p.source, outputs_mode, sizeof(outputs_mode) - 1);
    p.source_len = sizeof(outputs_mode) - 1;
    p.duration_s = 5;
    static const char *const teams[] = {"red", "blue"};
    /* game.start switches the siren on: its max on (30 s), as the script. */
    CHECK(node_runner_start(&r, &p, teams, 2));
    CHECK(o.game == OUT_GAME_RUNNING);
    CHECK(strstr(events, "\"capability\":\"siren\",\"ms\":30000,\"source\":\"script\"") != NULL);
    for (int i = 0; i < 50; i++) {
        node_runner_tick(&r, 10);
        now += 10;
        outputs_tick(&o, OUT_GAME_RUNNING, now);
    }
    CHECK(be[0].on);
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":100}"));
    CHECK(!o.ch[0].on && o.ch[1].on && o.ch[1].pattern && o.ch[1].on_ms == 500);
    CHECK(strstr(events, "\"capability\":\"smoke\"") == NULL);
    /* The timer runs out: every output off before game.end's handler, whose horn is the grace's. */
    events[0] = '\0';
    for (int i = 0; i < 460 && node_runner_status(&r) == ATALAIA_NODE_RUNNING; i++) {
        node_runner_tick(&r, 10);
        now += 10;
        outputs_tick(
            &o, node_runner_status(&r) == ATALAIA_NODE_ENDED ? OUT_GAME_ENDED : OUT_GAME_RUNNING,
            now);
    }
    CHECK(node_runner_status(&r) == ATALAIA_NODE_ENDED);
    CHECK(o.grace);
    CHECK(strcmp(events,
                 "output.switched {\"capability\":\"horn\",\"ms\":3000,\"source\":\"script\"}\n") ==
          0);
    CHECK(o.ch[1].on && !o.ch[1].pattern);
    node_runner_stop(&r);
    run(OUT_GAME_NONE, 3010);
    CHECK(!be[1].on);
    /* command_dispatch_output: an output's id is the box's; anything else is not. */
    CHECK(!command_dispatch_output(&o, "ring", "fill", "[\"red\"]"));
    CHECK(!command_dispatch_output(NULL, "siren", "on", "[]"));
    CHECK(command_dispatch_output(&o, "siren", "frobnicate", "[]"));
    CHECK(command_dispatch_output(&o, "siren", "pulse", "[]")); /* no duration: nothing */
}

void run_outputs_tests(void)
{
    test_defaults_and_settings();
    test_modules_text();
    test_disabled_text();
    test_only_while_a_game_runs();
    test_limits();
    test_patterns();
    test_game_state_rules();
    test_admin_test();
    test_script_rate();
    test_cmd_vectors();
    test_admin_screen();
    test_admin_console();
    test_mode_calls();
}
