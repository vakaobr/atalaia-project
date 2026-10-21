/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Reference-image tests for the on-board OLED's status view (oled_view.h)
 * and the USB radio modem's screens (modem_screen.h, the modem_* cases).
 * Each case draws one screen through the real LVGL 9.2.2 build on a
 * headless 128x64 display, packs it to one bit per pixel as the device does
 * (oled_pack), writes the result to <build>/screens/oled/ and compares it
 * with firmware/esp32/test/screens/oled/<name>.png.
 *
 * ATALAIA_UPDATE_SCREENS=1 rewrites the references, as for test_screens.c.
 */
#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "lvgl.h"
#include "modem/modem_screen.h"
#include "oled_view.h"
#include "png_io.h"

#define W HAL_OLED_WIDTH
#define H HAL_OLED_HEIGHT

typedef struct {
    const char *name; /* PNG file name without .png */
    const char *mode; /* the "@mode" message before it, or NULL */
    const char *template_name;
    const char *data;
} oled_case_t;

#define BOMB  "org.atalaia.bomb {\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300}"
#define MEDIC "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"en\"}"

/* "splash" is drawn by oled_view_splash(), not by a screen update. */
static const oled_case_t cases[] = {
    {"splash", NULL, NULL, NULL},
    {"pin_entry", NULL, "pin_entry", "{\"digits\":0,\"error\":false}"},
    {"pin_entry_typed", NULL, "pin_entry", "{\"digits\":3,\"error\":false}"},
    {"pin_entry_wrong", NULL, "pin_entry", "{\"digits\":0,\"error\":true}"},
    {"preset_select", NULL, "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\",\"Hold-All Domination\",\"Last Stand\",\"Codes\","
     "\"Kill Confirmed\",\"Respawn and Lives\",\"Player Check-in\",\"Medic Kit\"],"
     "\"selected\":3,\"page\":1,\"pages\":2}"},
    {"timer_adjust", NULL, "timer_adjust", "{\"timer_s\":600}"},
    {"start_confirm", NULL, "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}"},
    {"status", NULL, "status", "{\"title\":\"Game on\",\"mode\":\"Bomb\",\"timer_s\":600}"},
    {"status_invited", NULL, "status", "{\"title\":\"Invited\",\"mode\":\"3073: zone\"}"},
    {"status_ready", NULL, "status", "{\"title\":\"Ready\",\"mode\":\"next game\"}"},
    {"status_pair_locked", NULL, "status",
     "{\"title\":\"Pair locked\",\"pairing\":\"restart the box\"}"},
    {"status_pair", NULL, "status",
     "{\"title\":\"Pair this box\",\"code\":\"042 137\",\"id\":\"b0c5\",\"field\":\"none\"}"},
    {"standby", BOMB, "standby", "{\"arm\":\"red\"}"},
    {"standby_arming", BOMB, "standby", "{\"arm\":\"red\",\"progress\":0.6}"},
    {"countdown", BOMB, "countdown", "{\"left\":299}"},
    {"countdown_defusing", BOMB, "countdown", "{\"left\":231,\"defuse\":0.4}"},
    {"defused", BOMB, "defused", "{\"team\":\"blue\"}"},
    {"exploded", BOMB, "exploded", "{\"team\":\"red\"}"},
    {"code_entry", BOMB, "code_entry",
     "{\"title\":\"DEFUSE\",\"digits\":2,\"left\":61,\"message\":\"Enter your team code\"}"},
    {"mode_template", MEDIC, "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"Limit reached\",\"player\":\"r2\",\"team\":\"red\"}"},
    {"wifi_setup", NULL, "wifi_setup", "{\"ssid\":\"atalaia-7c4f\"}"},
};
#define CASE_COUNT ((int)(sizeof(cases) / sizeof(cases[0])))

/* The USB radio modem's screens: "modem_splash" is modem_screen_splash(). */
typedef struct {
    const char *name;
    modem_screen_state_t state;
} modem_case_t;

#define MODEM_COUNTS .tx = 1234, .tx_fail = 3, .rx = 56789, .rx_auth_fail = 1
static const modem_case_t modem_cases[] = {
    {"modem_splash", {0}},
    {"modem_waiting",
     {.link = MODEM_LINK_WAITING, .channel_hz = 869525000u, .radio_ok = true, .duty_ms = 360000}},
    {"modem_game",
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_link_down",
     {.link = MODEM_LINK_DOWN,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 869525000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 341200}},
    {"modem_no_duty",
     {.link = MODEM_LINK_UP,
      .configured = true,
      .game_id = 4660,
      .channel_hz = 868100000u,
      MODEM_COUNTS,
      .radio_ok = true,
      .duty_ms = 0}},
    {"modem_radio_fault",
     {.link = MODEM_LINK_UP,
      .channel_hz = 869525000u,
      .radio_ok = false,
      .fault = "SX1262 errors 0x0020 (TCXO)"}},
};
#define MODEM_CASE_COUNT ((int)(sizeof(modem_cases) / sizeof(modem_cases[0])))

_Alignas(64) static uint8_t framebuffer[W * H * 2];
static lv_display_t *display;
static uint32_t fake_ms;
static int failures;
static uint8_t rendered[W * H * 3];

static uint32_t tick_cb(void)
{
    return fake_ms;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    (void)px_map;
    lv_display_flush_ready(disp);
}

static void fail(const char *name, const char *msg)
{
    fprintf(stderr, "FAIL oled %s: %s\n", name, msg);
    failures++;
}

static bool update_mode(void)
{
    const char *v = getenv("ATALAIA_UPDATE_SCREENS");
    return v && v[0] == '1';
}

/* What the panel shows: lit pixels white, the rest black. */
static void capture(lv_obj_t *scr)
{
    lv_obj_invalidate(scr);
    lv_refr_now(display);

    static uint8_t fb[HAL_OLED_FB_SIZE];
    oled_pack((const uint16_t *)framebuffer, fb);
    for (int y = 0; y < H; y++) {
        for (int x = 0; x < W; x++) {
            uint8_t v = (fb[(y / 8) * W + x] >> (y % 8)) & 1 ? 255 : 0;
            memset(&rendered[3 * (y * W + x)], v, 3);
        }
    }
}

/* Draws the case, then captures it. */
static void render(const oled_case_t *c)
{
    lv_obj_t *scr = lv_screen_active();
    fake_ms += 10000;
    if (!c->template_name) {
        oled_view_splash(scr, "v0.2.0", fake_ms, 0);
    } else {
        if (c->mode) oled_view_handle(scr, "@mode", c->mode, fake_ms);
        oled_view_handle(scr, c->template_name, c->data, fake_ms);
    }
    capture(scr);
}

static void render_modem(const modem_case_t *c)
{
    lv_obj_t *scr = lv_screen_active();
    if (strcmp(c->name, "modem_splash") == 0) {
        modem_screen_splash(scr, "v0.2.0");
    } else {
        modem_screen_text_t t;
        modem_screen_text(&c->state, &t);
        modem_screen_draw(scr, &t);
    }
    capture(scr);
}

static void compare_with_reference(const char *name)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/%s.png", OLED_OUT_DIR, name);
    if (!png_write_rgb(path, W, H, rendered)) fail(name, "cannot write the rendered PNG");

    snprintf(path, sizeof(path), "%s/%s.png", OLED_REF_DIR, name);
    if (update_mode()) {
        if (!png_write_rgb(path, W, H, rendered)) fail(name, "cannot update the reference");
        printf("updated %s\n", path);
        return;
    }
    int rw = 0, rh = 0;
    uint8_t *ref = png_read_rgb(path, &rw, &rh);
    if (!ref) {
        fail(name, "no reference PNG; run with ATALAIA_UPDATE_SCREENS=1 to create it");
        return;
    }
    if (rw != W || rh != H) {
        fail(name, "the reference PNG is not 128x64");
    } else if (memcmp(ref, rendered, sizeof(rendered)) != 0) {
        int diff = 0;
        for (int i = 0; i < W * H; i++) diff += memcmp(&ref[3 * i], &rendered[3 * i], 3) != 0;
        fprintf(stderr, "  %d pixels differ; rendered: %s/%s.png\n", diff, OLED_OUT_DIR, name);
        fail(name, "differs from its reference; if intended, run with ATALAIA_UPDATE_SCREENS=1");
    }
    png_free(ref);
}

/* Every reference PNG must belong to a case, so stale images do not linger. */
static void check_no_stale_references(void)
{
    DIR *dir = opendir(OLED_REF_DIR);
    if (!dir) {
        fail("(all)", "cannot open the reference folder " OLED_REF_DIR);
        return;
    }
    struct dirent *e;
    while ((e = readdir(dir)) != NULL) {
        size_t len = strlen(e->d_name);
        if (len < 5 || strcmp(e->d_name + len - 4, ".png") != 0) continue;
        bool known = false;
        for (int i = 0; i < CASE_COUNT; i++) {
            if (strlen(cases[i].name) == len - 4 && strncmp(cases[i].name, e->d_name, len - 4) == 0)
                known = true;
        }
        for (int i = 0; i < MODEM_CASE_COUNT; i++) {
            const char *n = modem_cases[i].name;
            if (strlen(n) == len - 4 && strncmp(n, e->d_name, len - 4) == 0) known = true;
        }
        if (!known) fail(e->d_name, "reference PNG without a test case; delete it or add a case");
    }
    closedir(dir);
}

/* The splash holds later screens until its time is over. */
static void check_splash_hold(void)
{
    lv_obj_t *scr = lv_screen_active();
    oled_view_splash(scr, "v0.2.0", 1000, 2000);
    oled_view_handle(scr, "pin_entry", "{\"digits\":0}", 1500);
    lv_obj_t *first = lv_obj_get_child(scr, 0);
    if (!first || !lv_obj_check_type(first, &lv_image_class))
        fail("splash", "a screen replaced it early");
    oled_view_poll(scr, 2999);
    first = lv_obj_get_child(scr, 0);
    if (!first || !lv_obj_check_type(first, &lv_image_class))
        fail("splash", "gone before its time");
    oled_view_poll(scr, 3000);
    first = lv_obj_get_child(scr, 0);
    if (first && lv_obj_check_type(first, &lv_image_class))
        fail("splash", "the held screen never came");
}

int main(void)
{
    char parent[512];
    snprintf(parent, sizeof(parent), "%s", OLED_OUT_DIR);
    char *slash = strrchr(parent, '/');
    if (slash) *slash = '\0';
    mkdir(parent, 0755);
    mkdir(OLED_OUT_DIR, 0755);
    lv_init();
    lv_tick_set_cb(tick_cb);
    display = lv_display_create(W, H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, framebuffer, NULL, sizeof(framebuffer),
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush_cb);

    for (int i = 0; i < CASE_COUNT; i++) {
        render(&cases[i]);
        compare_with_reference(cases[i].name);
    }
    for (int i = 0; i < MODEM_CASE_COUNT; i++) {
        render_modem(&modem_cases[i]);
        compare_with_reference(modem_cases[i].name);
    }
    check_splash_hold();
    if (!update_mode()) check_no_stale_references();

    if (failures) {
        fprintf(stderr, "oled screens: %d failure(s)\n", failures);
        return 1;
    }
    printf("oled screens: %d renders match their reference images (%s)\n",
           CASE_COUNT + MODEM_CASE_COUNT, OLED_OUT_DIR);
    return 0;
}
