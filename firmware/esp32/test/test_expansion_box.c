/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the expansion port in the box's game (expansion_box.c; draft RFC "The expansion
 * port", increment 8): simulated modules on the real module core (module_sim.c) behind a fake
 * bus, the port driver, the output layer and box_game's node.modules text. Hits reach the script
 * only while a game runs and the script armed the channel; a second hit channel adds "channel";
 * arming is kept by capability id; a module lost during a game is node.module_lost; a module's
 * output channels join the output layer disabled, named beside the simple outputs, and reach the
 * module's relays with their duration and pattern; they leave with the module.
 */
#include <stdio.h>
#include <string.h>

#include "box_game.h"
#include "check.h"
#include "expansion_box.h"
#include "module_sim.h"
#include "outputs.h"

/* ---- A fake bus with simulated modules ---------------------------------------------------- */

static module_sim_t sims[EXP_ADDR_COUNT];
static bool plugged[EXP_ADDR_COUNT];
static uint32_t now;

static module_sim_t *sim_at(uint8_t addr)
{
    if (addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST) return NULL;
    return plugged[addr - EXP_ADDR_FIRST] ? &sims[addr - EXP_ADDR_FIRST] : NULL;
}

static bool f_probe(void *ctx, uint8_t addr)
{
    (void)ctx;
    return sim_at(addr) != NULL;
}

static int f_write(void *ctx, uint8_t addr, const uint8_t *d, size_t n)
{
    (void)ctx;
    module_sim_t *m = sim_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, now, d, n);
    return EXP_BUS_OK;
}

static int f_write_read(void *ctx, uint8_t addr, const uint8_t *o, size_t on, uint8_t *in,
                        size_t inn)
{
    (void)ctx;
    module_sim_t *m = sim_at(addr);
    if (m == NULL) return EXP_BUS_FAIL;
    module_sim_write(m, now, o, on);
    module_sim_read(m, now, in, inn);
    return EXP_BUS_OK;
}

static module_sim_t *plug(const char *name, uint8_t addr)
{
    int i = addr - EXP_ADDR_FIRST;
    CHECK(module_sim_named(&sims[i], name, addr, now));
    plugged[i] = true;
    return &sims[i];
}

/* ---- What the box tells ------------------------------------------------------------------ */

static char inputs[8][64];
static int input_count;
static char events[8][160];
static int event_count;

static void x_input(void *ctx, const char *type, const char *data)
{
    (void)ctx;
    if (input_count < 8) snprintf(inputs[input_count++], sizeof(inputs[0]), "%s %s", type, data);
}

static void x_event(void *ctx, const char *type, const char *data)
{
    (void)ctx;
    if (event_count < 8) snprintf(events[event_count++], sizeof(events[0]), "%s %s", type, data);
}

static expansion_box_t xb;
static outputs_t outs;

typedef struct {
    bool on;
} fake_simple_t;

static void fake_drive(void *ctx, bool on, bool live, uint32_t t)
{
    (void)live;
    (void)t;
    ((fake_simple_t *)ctx)->on = on;
}

static fake_simple_t simple_be;

/* A box with (or without) a simple output "siren" on GPIO 46, and its port started at t = 0. */
static void setup(bool with_simple)
{
    memset(sims, 0, sizeof(sims));
    memset(plugged, 0, sizeof(plugged));
    input_count = event_count = 0;
    now = 0;
    outputs_init(&outs, NULL);
    if (with_simple) {
        out_backend_t be = {.ctx = &simple_be, .drive = fake_drive, .set = NULL};
        out_settings_t s;
        outputs_default_settings(0, &s);
        s.enabled = true;
        snprintf(s.function, sizeof(s.function), "siren");
        CHECK(outputs_add_simple(&outs, 46, &be, &s) == 0);
    }
    exp_bus_t bus = {NULL, f_probe, f_write, f_write_read};
    xb_ops_t ops = {NULL, x_input, x_event, NULL};
    expansion_box_init(&xb, &bus, &outs, &ops);
}

static void start(void)
{
    expansion_box_start(&xb, now);
}

/* The game task's turns, every 10 ms, to t. */
static void run_to(out_game_t game, uint32_t t)
{
    while (now < t) {
        now += 10;
        outputs_tick(&outs, game, now);
        expansion_box_tick(&xb, game, now);
    }
}

/* ---- Hits ---------------------------------------------------------------------------------- */

static void test_hits_reach_the_script_while_armed_and_running(void)
{
    setup(false);
    module_sim_t *t = plug("target", 0x58);
    start();
    CHECK(expansion_box_has_hit(&xb));
    run_to(OUT_GAME_NONE, 100);
    /* Not armed between games: the module drops the hit itself. */
    CHECK(!module_sim_hit(t, now, 0, MC_EVENT_HIT, 120));
    /* The game starts and the mode's game.start arms it (cap("hit"):arm()). */
    CHECK(expansion_box_command(&xb, "hit", "arm"));
    run_to(OUT_GAME_RUNNING, 200);
    CHECK(module_sim_armed(t) == 1);
    CHECK(module_sim_hit(t, now, 0, MC_EVENT_HIT, 120));
    run_to(OUT_GAME_RUNNING, 260);
    CHECK(input_count == 1 && strcmp(inputs[0], "hit.hit {\"strength\":120}") == 0);
    CHECK(xb.hits == 1);
    /* Paused: disarmed (a hit then never counts), armed again on resume. */
    run_to(OUT_GAME_PAUSED, 300);
    CHECK(module_sim_armed(t) == 0);
    CHECK(!module_sim_hit(t, now, 0, MC_EVENT_HIT, 50));
    run_to(OUT_GAME_RUNNING, 340);
    CHECK(module_sim_armed(t) == 1);
    /* The script disarms it. */
    CHECK(expansion_box_command(&xb, "hit", "disarm"));
    run_to(OUT_GAME_RUNNING, 380);
    CHECK(module_sim_armed(t) == 0);
    /* The game's end forgets what the script armed. */
    CHECK(expansion_box_command(&xb, "hit", "arm"));
    run_to(OUT_GAME_RUNNING, 420);
    run_to(OUT_GAME_ENDED, 460);
    CHECK(xb.armed == 0 && module_sim_armed(t) == 0);
    /* Not a hit capability: left to command_dispatch. */
    CHECK(!expansion_box_command(&xb, "ring", "fill"));
    CHECK(!expansion_box_command(&xb, "hit.9", "arm"));
    CHECK(!expansion_box_command(&xb, "hit.1", "arm"));
    CHECK(expansion_box_hit_number("hit") == 1 && expansion_box_hit_number("hit.2") == 2);
    CHECK(expansion_box_hit_number("hitx") == 0 && expansion_box_hit_number(NULL) == 0);
}

static void test_two_targets_name_their_channel(void)
{
    setup(false);
    module_sim_t *a = plug("target", 0x58);
    module_sim_t *b = plug("target", 0x59);
    start();
    CHECK(strcmp(xb.exp.mod[0].cap[0], "hit") == 0 || strcmp(xb.exp.mod[1].cap[0], "hit") == 0);
    /* Only hit.2 armed: the first target's hits are dropped on the module. */
    CHECK(expansion_box_command(&xb, "hit.2", "arm"));
    run_to(OUT_GAME_RUNNING, 100);
    CHECK(module_sim_armed(a) == 0 && module_sim_armed(b) == 1);
    CHECK(module_sim_hit(b, now, 0, MC_EVENT_HIT, 200));
    run_to(OUT_GAME_RUNNING, 160);
    CHECK(input_count == 1 && strcmp(inputs[0], "hit.hit {\"strength\":200,\"channel\":2}") == 0);
}

static void test_a_target_plugged_in_during_a_game_is_armed_at_once(void)
{
    setup(false);
    start();
    CHECK(!expansion_box_has_hit(&xb));
    /* The mode armed "hit" at game.start, before any target was there. */
    CHECK(expansion_box_command(&xb, "hit", "arm"));
    run_to(OUT_GAME_RUNNING, 100);
    module_sim_t *t = plug("target", 0x58);
    run_to(OUT_GAME_RUNNING, 2400); /* found within 2 s, armed at the next turn */
    CHECK(expansion_box_has_hit(&xb) && module_sim_armed(t) == 1);
    CHECK(xb.changes >= 1);
}

static void test_a_module_lost_during_a_game(void)
{
    setup(false);
    plug("target", 0x58);
    start();
    run_to(OUT_GAME_NONE, 100);
    /* Lost between games: node.modules says so (box_game), no node.module_lost. */
    plugged[0] = false;
    run_to(OUT_GAME_NONE, 800);
    CHECK(!expansion_box_has_hit(&xb) && event_count == 0 && xb.lost == 1);
    plug("target", 0x58);
    run_to(OUT_GAME_RUNNING, 3000);
    CHECK(expansion_box_has_hit(&xb));
    plugged[0] = false;
    run_to(OUT_GAME_RUNNING, 3700);
    CHECK(event_count == 1);
    CHECK(
        strcmp(events[0],
               "node.module_lost {\"modules\":\"58:target/1.0.0:hit\",\"reason\":\"no_answer\"}") ==
        0);
}

/* ---- Outputs ------------------------------------------------------------------------------- */

static void test_a_modules_outputs_join_the_output_layer(void)
{
    setup(true);
    module_sim_t *m = plug("out4", 0x5C);
    start();
    run_to(OUT_GAME_NONE, 50);
    CHECK(outs.count == 5 && outs.simple == 1);
    /* The simple output keeps "siren"; the module's siren is siren.2; disabled (EXP-28). */
    CHECK(strcmp(outs.ch[0].id, "siren") == 0 && strcmp(outs.ch[1].id, "siren.2") == 0);
    CHECK(strcmp(outs.ch[2].id, "strobe") == 0 && strcmp(outs.ch[3].id, "smoke") == 0 &&
          strcmp(outs.ch[4].id, "out.4") == 0);
    CHECK(!outs.ch[1].set.enabled && outs.ch[3].set.max_on_s == 30); /* the module's 30 s */
    CHECK(outputs_enabled_count(&outs) == 1);
    /* The driver's entry follows the output layer's names. */
    char text[OUT_MODULES_MAX + 1];
    expansion_box_modules_text(&xb, text, sizeof(text));
    CHECK(strcmp(text, "5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    box_game_t g;
    memset(&g, 0, sizeof(g));
    g.outputs = &outs;
    g.port = &xb;
    box_game_modules_text(&g, text, sizeof(text));
    CHECK(strcmp(text, "g46:servo:siren;5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    /* Above the module's own max on: refused. */
    out_settings_t s = outs.ch[3].set;
    s.max_on_s = 31;
    CHECK(outputs_configure(&outs, 3, &s) == OUT_BAD_ARGS);
    /* The admin enables the strobe; the game pulses it: the module's relay goes on for 1.5 s. */
    s = outs.ch[2].set;
    s.enabled = true;
    CHECK(outputs_configure(&outs, 2, &s) == OUT_OK);
    CHECK(outputs_switch(&outs, "siren.2", OUT_ACT_PULSE, 1000, 0, 0, OUT_SRC_SCRIPT) ==
          OUT_DISABLED);
    run_to(OUT_GAME_RUNNING, 100);
    CHECK(outputs_switch(&outs, "strobe", OUT_ACT_PULSE, 1500, 0, 0, OUT_SRC_FIELD) == OUT_OK);
    run_to(OUT_GAME_RUNNING, 400);
    uint8_t on = 0;
    module_sim_state(m, now, &on, NULL);
    CHECK(on == 0x02);
    run_to(OUT_GAME_RUNNING, 1700);
    module_sim_state(m, now, &on, NULL);
    CHECK(on == 0);
    /* A pattern: down to the relay's 100 ms (not the simple output's 500 ms), run by the module. */
    CHECK(outputs_switch(&outs, "strobe", OUT_ACT_PATTERN, 2000, 50, 200, OUT_SRC_FIELD) ==
          OUT_BAD_ARGS);
    CHECK(outputs_switch(&outs, "strobe", OUT_ACT_PATTERN, 2000, 200, 200, OUT_SRC_FIELD) ==
          OUT_OK);
    run_to(OUT_GAME_RUNNING, 1800);
    CHECK(m->core.out[1].mode == MC_MODE_PATTERN);
    /* The pause turns it off on the module. */
    run_to(OUT_GAME_PAUSED, 2000);
    module_sim_state(m, now, &on, NULL);
    CHECK(on == 0 && m->core.out[1].mode == MC_MODE_OFF);
    /* The module is lost: its channels leave; the simple output stays. */
    plugged[0x5C - EXP_ADDR_FIRST] = false;
    run_to(OUT_GAME_NONE, 9000);
    CHECK(outs.count == 1 && outs.simple == 1 && strcmp(outs.ch[0].id, "siren") == 0);
    CHECK(outputs_find(&outs, "strobe") < 0);
    box_game_modules_text(&g, text, sizeof(text));
    CHECK(strcmp(text, "g46:servo:siren") == 0);
}

/* A module's output channels left disabled (EXPI8-7: every one until the admin enables it) are in
 * node.outputs_disabled (EXPL-20): its entry with only those ids, after the simple outputs not
 * enabled, whole entries within 100 bytes; enabling one at the box changes the text (and no
 * node.modules entry); a lost module leaves it. */
static void test_a_modules_channels_left_disabled(void)
{
    setup(true);
    out_backend_t be = {.ctx = &simple_be, .drive = fake_drive, .set = NULL};
    out_settings_t s;
    outputs_default_settings(1, &s);
    snprintf(s.function, sizeof(s.function), "horn"); /* fitted, not enabled */
    CHECK(outputs_add_simple(&outs, 45, &be, &s) == 1);
    plug("out4", 0x5C);
    start();
    run_to(OUT_GAME_NONE, 50);
    CHECK(outs.count == 6 && outs.simple == 2);
    char text[OUT_MODULES_MAX + 1];
    CHECK(expansion_box_disabled_text(&xb, text, sizeof(text)) ==
          strlen("5c:out4/1.0.0:siren.2,strobe,smoke,out.4"));
    CHECK(strcmp(text, "5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    box_game_t g;
    memset(&g, 0, sizeof(g));
    g.outputs = &outs;
    g.port = &xb;
    box_game_disabled_text(&g, text, sizeof(text));
    CHECK(strcmp(text, "g45:servo:horn;5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    /* node.modules is unchanged by the settings: the module's entry lists its usable channels. */
    char mods[OUT_MODULES_MAX + 1];
    box_game_modules_text(&g, mods, sizeof(mods));
    CHECK(strcmp(mods, "g46:servo:siren;5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    /* The admin enables the strobe: it leaves the text; node.modules stays as it was. */
    s = outs.ch[3].set;
    CHECK(strcmp(outs.ch[3].id, "strobe") == 0);
    s.enabled = true;
    CHECK(outputs_configure(&outs, 3, &s) == OUT_OK);
    box_game_disabled_text(&g, text, sizeof(text));
    CHECK(strcmp(text, "g45:servo:horn;5c:out4/1.0.0:siren.2,smoke,out.4") == 0);
    box_game_modules_text(&g, text, sizeof(text));
    CHECK(strcmp(text, mods) == 0);
    /* Every channel enabled: the module has no entry; the horn alone is left. */
    for (int i = outs.simple; i < outs.count; i++) {
        s = outs.ch[i].set;
        s.enabled = true;
        CHECK(outputs_configure(&outs, i, &s) == OUT_OK);
    }
    CHECK(expansion_box_disabled_text(&xb, text, sizeof(text)) == 0 && text[0] == '\0');
    box_game_disabled_text(&g, text, sizeof(text));
    CHECK(strcmp(text, "g45:servo:horn") == 0);

    /* Two modules: whole entries only, within 100 bytes. A second out4's entry
     * ("5d:out4/1.0.0:siren.3,strobe.2,smoke.2,out.4.2", 47 bytes) does not fit after the
     * simple ones and the first module's (14 + 1 + 41 + 1 + 47 > 100): it is left out whole. */
    setup(true);
    CHECK(outputs_add_simple(&outs, 45, &be, NULL) == 1); /* a new box's: out.2, disabled */
    plug("out4", 0x5C);
    plug("out4", 0x5D);
    start();
    run_to(OUT_GAME_NONE, 50);
    CHECK(outs.count == 10);
    char both[EXP_MODULES_TEXT_MAX + 1];
    expansion_box_disabled_text(&xb, both, sizeof(both));
    CHECK(strcmp(both, "5c:out4/1.0.0:siren.2,strobe,smoke,out.4;"
                       "5d:out4/1.0.0:siren.3,strobe.2,smoke.2,out.4.2") == 0);
    memset(&g, 0, sizeof(g));
    g.outputs = &outs;
    g.port = &xb;
    size_t n = box_game_disabled_text(&g, text, sizeof(text));
    CHECK(n <= OUT_MODULES_MAX && n == strlen(text));
    CHECK(strcmp(text, "g45:servo:out.2;5c:out4/1.0.0:siren.2,strobe,smoke,out.4") == 0);
    /* A small buffer: whole entries only, never a cut one. */
    char small[20];
    CHECK(box_game_disabled_text(&g, small, sizeof(small)) == strlen("g45:servo:out.2"));
    CHECK(strcmp(small, "g45:servo:out.2") == 0);

    /* The first module is lost: its channels leave the text with it. */
    plugged[0x5C - EXP_ADDR_FIRST] = false;
    run_to(OUT_GAME_NONE, 9000);
    box_game_disabled_text(&g, text, sizeof(text));
    const char *left = "g45:servo:out.2;5d:out4/1.0.0:";
    CHECK(strncmp(text, left, strlen(left)) == 0);
    CHECK(strstr(text, "5c:") == NULL);
}

/* The box's max on is never above the module's: an on without a time ends on the box's side at
 * the module's max on (so the module's min off, which follows only its own max on, never comes). */
static void test_an_on_ends_at_the_modules_max_on(void)
{
    setup(false);
    module_sim_t *m = plug("out4", 0x5C);
    start();
    out_settings_t s = outs.ch[2].set; /* smoke: 30 s max on, then 30 s off */
    CHECK(strcmp(outs.ch[2].id, "smoke") == 0);
    s.enabled = true;
    CHECK(outputs_configure(&outs, 2, &s) == OUT_OK);
    run_to(OUT_GAME_RUNNING, 100);
    CHECK(outputs_switch(&outs, "smoke", OUT_ACT_ON, 0, 0, 0, OUT_SRC_GM) == OUT_OK);
    run_to(OUT_GAME_RUNNING, 29000);
    uint8_t on = 0;
    module_sim_state(m, now, &on, NULL);
    CHECK((on & 0x04) != 0);
    run_to(OUT_GAME_RUNNING, 30300);
    module_sim_state(m, now, &on, NULL);
    CHECK((on & 0x04) == 0 && !outs.ch[2].on);
    CHECK(outputs_switch(&outs, "smoke", OUT_ACT_PULSE, 5000, 0, 0, OUT_SRC_GM) == OUT_OK);
    run_to(OUT_GAME_RUNNING, 30600);
    module_sim_state(m, now, &on, NULL);
    CHECK((on & 0x04) != 0);
}

static void test_status_json(void)
{
    setup(false);
    plug("target", 0x58);
    start();
    char json[400];
    expansion_box_status_json(&xb, json, sizeof(json));
    const char *want =
        "[{\"address\":\"58\",\"model\":\"target\",\"fw\":\"1.0.0\",\"caps\":[\"hit\"]";
    CHECK(strncmp(json, want, strlen(want)) == 0);
    setup(false);
    start();
    expansion_box_status_json(&xb, json, sizeof(json));
    CHECK(strcmp(json, "[]") == 0);
}

void run_expansion_box_tests(void)
{
    test_hits_reach_the_script_while_armed_and_running();
    test_two_targets_name_their_channel();
    test_a_target_plugged_in_during_a_game_is_armed_at_once();
    test_a_module_lost_during_a_game();
    test_a_modules_outputs_join_the_output_layer();
    test_a_modules_channels_left_disabled();
    test_an_on_ends_at_the_modules_max_on();
    test_status_json();
}
