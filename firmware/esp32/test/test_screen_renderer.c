/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for screen_renderer template routing and data recording.
 * Verifies all 9 known templates, unknown template rejection,
 * NULL data handling, and sequential render call counting.
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "screen_renderer.h"

/* ---- individual template tests ---- */

static void test_render_standby(void)
{
    screen_renderer_reset();
    CHECK(screen_render("standby", "{\"arm\":\"red\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "standby") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"arm\":\"red\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_countdown(void)
{
    screen_renderer_reset();
    CHECK(screen_render("countdown", "{\"left\":42}"));
    CHECK(strcmp(screen_renderer_last_template(), "countdown") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"left\":42}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_defused(void)
{
    screen_renderer_reset();
    CHECK(screen_render("defused", "{\"team\":\"blue\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "defused") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"team\":\"blue\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_exploded(void)
{
    screen_renderer_reset();
    CHECK(screen_render("exploded", "{\"team\":\"red\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "exploded") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"team\":\"red\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_final_score(void)
{
    screen_renderer_reset();
    CHECK(screen_render("final_score", "{\"owner\":\"red\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "final_score") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"owner\":\"red\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_paused(void)
{
    screen_renderer_reset();
    CHECK(screen_render("paused", "{}"));
    CHECK(strcmp(screen_renderer_last_template(), "paused") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_status(void)
{
    screen_renderer_reset();
    CHECK(screen_render("status", "{\"battery\":85,\"version\":\"1.0\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "status") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"battery\":85,\"version\":\"1.0\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_preset_select(void)
{
    screen_renderer_reset();
    CHECK(screen_render("preset_select", "{\"presets\":[\"bomb\",\"dom\"]}"));
    CHECK(strcmp(screen_renderer_last_template(), "preset_select") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"presets\":[\"bomb\",\"dom\"]}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_wifi_setup(void)
{
    screen_renderer_reset();
    CHECK(screen_render("wifi_setup", "{\"ssid\":\"atalaia-setup\"}"));
    CHECK(strcmp(screen_renderer_last_template(), "wifi_setup") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"ssid\":\"atalaia-setup\"}") == 0);
    CHECK(screen_renderer_call_count() == 1);
}

/* ---- edge cases ---- */

static void test_render_unknown_template(void)
{
    screen_renderer_reset();
    CHECK(!screen_render("nonexistent_template", "{}"));
    CHECK(screen_renderer_call_count() == 0);
    CHECK(screen_renderer_last_template()[0] == '\0');
}

static void test_render_null_data(void)
{
    screen_renderer_reset();
    CHECK(screen_render("standby", NULL));
    CHECK(strcmp(screen_renderer_last_template(), "standby") == 0);
    CHECK(screen_renderer_last_data()[0] == '\0');
    CHECK(screen_renderer_call_count() == 1);
}

static void test_render_sequential_calls(void)
{
    screen_renderer_reset();
    CHECK(screen_render("standby", "{\"arm\":\"red\"}"));
    CHECK(screen_render("countdown", "{\"left\":10}"));
    CHECK(screen_render("exploded", "{\"team\":\"red\"}"));
    CHECK(screen_renderer_call_count() == 3);
    /* Last rendered should be exploded. */
    CHECK(strcmp(screen_renderer_last_template(), "exploded") == 0);
    CHECK(strcmp(screen_renderer_last_data(), "{\"team\":\"red\"}") == 0);
}

/* ---- entry point ---- */

void run_screen_renderer_tests(void)
{
    test_render_standby();
    test_render_countdown();
    test_render_defused();
    test_render_exploded();
    test_render_final_score();
    test_render_paused();
    test_render_status();
    test_render_preset_select();
    test_render_wifi_setup();
    test_render_unknown_template();
    test_render_null_data();
    test_render_sequential_calls();
}
