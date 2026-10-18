/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The LVGL renderer for declarative screen templates (main/screen_template.c)
 * with the templates built into the image: every one parses, the running
 * mode picks them (main mode first), widgets are built once and only the
 * changed ones are patched, and without a template the C screens are drawn.
 * Pixels are compared in test_screens.c.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/screen_template.h"
#include "builtin_screens.h"
#include "check.h"
#include "screen_renderer.h"
#include "screen_template.h"
#include "test_display.h"

static atalaia_tpl_t tpl;

static const char *BOMB = "org.atalaia.bomb {\"attackers\":\"red\",\"fuse_s\":300}";

static void test_every_builtin_template_parses(void)
{
    CHECK(builtin_screen_count == 10);
    for (int i = 0; i < builtin_screen_count; i++) {
        const builtin_screen_t *s = &builtin_screens[i];
        char err[160];
        bool ok = atalaia_tpl_parse(&tpl, s->yaml, s->len, err, sizeof(err));
        if (!ok) fprintf(stderr, "FAIL %s/%s: %s\n", s->mode_id, s->name, err);
        CHECK(ok);
        CHECK(strlen(s->yaml) == s->len);
        CHECK(ok && strcmp(atalaia_tpl_str(&tpl, tpl.name), s->name) == 0);
    }
}

static void test_mode_picks_templates(void)
{
    screen_renderer_reset();
    CHECK(screen_template_find("countdown") == NULL); /* no mode yet */
    CHECK(screen_render(SCREEN_MODE_MESSAGE, BOMB));
    CHECK(strcmp(screen_template_mode(), "org.atalaia.bomb") == 0);
    CHECK(strcmp(screen_template_params(), "{\"attackers\":\"red\",\"fuse_s\":300}") == 0);
    const builtin_screen_t *s = screen_template_find("countdown");
    CHECK(s != NULL && strcmp(s->mode_id, "org.atalaia.bomb") == 0);
    CHECK(screen_template_find("code_entry") == NULL); /* stays a C screen */
    CHECK(screen_template_find("captured") == NULL);   /* Domination's */
    /* The mode message is not a screen. */
    CHECK(screen_renderer_call_count() == 0);

    /* A main mode with a modifier: the main mode's templates, then the modifier's. */
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.domination+org.atalaia.codes {}");
    s = screen_template_find("standby");
    CHECK(s != NULL && strcmp(s->mode_id, "org.atalaia.domination") == 0);
    CHECK(screen_template_find("countdown") == NULL);
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.codes+org.atalaia.bomb {}");
    s = screen_template_find("countdown");
    CHECK(s != NULL && strcmp(s->mode_id, "org.atalaia.bomb") == 0);
    /* A mode without templates, or none at all. */
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.holdall {}");
    CHECK(screen_template_find("final_score") == NULL);
    screen_render(SCREEN_MODE_MESSAGE, "");
    CHECK(screen_template_find("standby") == NULL);
    /* Parameters too long for the message arrive as "{}". */
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.bomb");
    CHECK(strcmp(screen_template_params(), "{}") == 0);
}

static void test_build_and_patch(void)
{
    test_display_init();
    screen_renderer_reset();
    screen_render(SCREEN_MODE_MESSAGE, BOMB);
    CHECK(screen_render("countdown", "{\"left\":299}"));
    CHECK(strcmp(screen_renderer_last_template(), "countdown") == 0);
    lv_obj_t *time_left = screen_template_widget("time_left");
    lv_obj_t *bar = screen_template_widget("fuse_bar");
    CHECK(time_left != NULL && bar != NULL);
    CHECK(time_left && strcmp(lv_label_get_text(time_left), "4:59") == 0);
    test_display_render();

    /* One second later: only the time and the bar change. */
    CHECK(screen_render("countdown", "{\"left\":298}"));
    CHECK(screen_template_widget("time_left") == time_left); /* patched, not rebuilt */
    CHECK(strcmp(lv_label_get_text(time_left), "4:58") == 0);
    CHECK(screen_template_changed() == 2);
    /* The same data: nothing changes. */
    CHECK(screen_render("countdown", "{\"left\":298}"));
    CHECK(screen_template_changed() == 0);
    /* The last ten seconds: the time turns red (its colour changes, the text too). */
    CHECK(screen_render("countdown", "{\"left\":9}"));
    CHECK(strcmp(lv_label_get_text(time_left), "0:09") == 0);
    CHECK(lv_color_to_u32(lv_obj_get_style_text_color(time_left, 0)) ==
          lv_color_to_u32(lv_color_hex(0xE53935)));
    /* With team codes the arming team shows: its label appears. */
    CHECK(screen_render("countdown", "{\"left\":9,\"team\":\"blue\"}"));
    CHECK(screen_template_changed() == 2); /* the bar's colour and the hidden label */

    /* Another template of the same mode: rebuilt. */
    CHECK(screen_render("exploded", "{\"team\":\"red\"}"));
    CHECK(screen_template_widget("time_left") == NULL);
    test_display_render();
}

static void test_fallback_to_c_screens(void)
{
    test_display_init();
    /* No mode: the C countdown. */
    screen_renderer_reset();
    CHECK(screen_render("countdown", "{\"left\":299}"));
    CHECK(screen_template_widget("time_left") == NULL);
    /* A template name only a mode has: unknown without the mode. */
    CHECK(!screen_render("captured", "{\"team\":\"red\"}"));
    /* Bomb with Codes: code_entry stays C, countdown is the template. */
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.bomb+org.atalaia.codes {\"fuse_s\":60}");
    CHECK(screen_render("code_entry", "{\"title\":\"CODE\",\"digits\":2}"));
    CHECK(screen_template_widget("time_left") == NULL);
    CHECK(screen_render("countdown", "{\"left\":30}"));
    CHECK(screen_template_widget("time_left") != NULL);
    CHECK(screen_render("code_entry", "{\"title\":\"CODE\",\"digits\":3}"));
    CHECK(screen_template_widget("time_left") == NULL);
    test_display_render();
    /* A new mode forgets what is shown: the same name is redrawn from its template. */
    screen_render(SCREEN_MODE_MESSAGE, "org.atalaia.domination {\"capture_hold_ms\":3000}");
    CHECK(screen_render("standby", "{}"));
    test_display_render();
    screen_renderer_reset();
}

void run_screen_template_tests(void)
{
    test_every_builtin_template_parses();
    test_mode_picks_templates();
    test_build_and_patch();
    test_fallback_to_c_screens();
}
