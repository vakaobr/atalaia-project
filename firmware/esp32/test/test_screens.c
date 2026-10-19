/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Reference-image tests for the screen templates. Each case renders one
 * template with representative data through the real LVGL 9.2.2 build
 * (headless, 320x240 RGB565), writes the result to <build>/screens/ and
 * compares it pixel by pixel with firmware/esp32/test/screens/<name>.png.
 *
 * To accept new renders on purpose, run with ATALAIA_UPDATE_SCREENS=1:
 *   ATALAIA_UPDATE_SCREENS=1 ctest --test-dir <build> -R screens
 * (or `python tools/docker_fw.py test --update-screens`), then look at
 * every changed PNG before committing it.
 */
#define _POSIX_C_SOURCE 200809L

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "lvgl.h"
#include "png_io.h"
#include "screen_renderer.h"
#include "screen_template.h"
#include "test_display.h"

#define W TEST_DISPLAY_W
#define H TEST_DISPLAY_H

typedef struct {
    const char *name; /* PNG file name without .png */
    const char *template_name;
    const char *data;
    /* For a mode's YAML template (modes/<mode>/assets/screens/): the "@mode"
     * message, "<mode id> <params>"; NULL for the C screens. */
    const char *mode;
} screen_case_t;

#define BOMB     "org.atalaia.bomb {\"attackers\":\"red\",\"defenders\":\"blue\",\"fuse_s\":300}"
#define DOM      "org.atalaia.domination {\"capture_hold_ms\":3000,\"tick_s\":10}"
#define KILL     "org.atalaia.kill_confirmed {\"turn_in_s\":20}"
#define RESPAWN  "org.atalaia.respawn {\"lives\":20,\"per_player\":false}"
#define CHECKIN  "org.atalaia.player_checkin {\"points\":1}"
#define MEDIC    "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"pt\"}"
#define MEDIC_EN "org.atalaia.medic {\"heal_hold_s\":10,\"charges\":5,\"lang\":\"en\"}"

/* Data as the modes (modes/bomb, modes/domination, modes/codes) and the shell send it. */
static const screen_case_t cases[] = {
    {"standby", "standby", "{\"arm\":\"red\"}", NULL},
    {"countdown", "countdown", "{\"left\":299}", NULL},
    {"countdown_last_seconds", "countdown", "{\"left\":7}", NULL},
    {"countdown_long", "countdown", "{\"left\":5400,\"team\":\"red\"}", NULL},
    {"defused", "defused", "{\"team\":\"blue\"}", NULL},
    {"defused_yellow", "defused", "{\"team\":\"yellow\"}", NULL},
    {"exploded", "exploded", "{\"team\":\"red\"}", NULL},
    {"final_score", "final_score", "{\"owner\":\"red\"}", NULL},
    {"final_score_no_owner", "final_score", "{}", NULL},
    {"paused", "paused", "{}", NULL},
    {"code_entry", "code_entry",
     "{\"title\":\"ARM\",\"digits\":0,\"message\":\"Enter your team code\"}", NULL},
    {"code_entry_defuse", "code_entry", "{\"title\":\"DEFUSE\",\"digits\":3,\"left\":154}", NULL},
    {"code_entry_wrong", "code_entry",
     "{\"title\":\"CODE\",\"digits\":0,\"message\":\"Wrong code\",\"error\":true}", NULL},
    {"code_entry_points", "code_entry",
     "{\"title\":\"CODE\",\"digits\":4,\"message\":\"+50 points for RED\",\"error\":false}", NULL},
    {"status", "status",
     "{\"title\":\"Game on\",\"mode\":\"Domination\",\"timer_s\":600,\"battery\":85,"
     "\"version\":\"0.1.0\"}",
     NULL},
    {"pin_entry", "pin_entry", "{\"digits\":2,\"error\":false}", NULL},
    {"pin_entry_wrong", "pin_entry", "{\"digits\":0,\"error\":true}", NULL},
    {"preset_select", "preset_select", "{\"presets\":[\"Bomb\",\"Domination\"],\"selected\":1}",
     NULL},
    {"preset_select_long", "preset_select",
     "{\"presets\":[\"Bomb\",\"Domination\",\"Bomb (short fuse)\",\"Domination: 3 teams\","
     "\"Night game with a very long name that does not fit\",\"Training\",\"King of the hill\"],"
     "\"selected\":5}",
     NULL},
    {"preset_select_empty", "preset_select", "{\"presets\":[],\"selected\":1}", NULL},
    {"timer_adjust", "timer_adjust", "{\"timer_s\":600}", NULL},
    {"timer_adjust_no_limit", "timer_adjust", "{\"timer_s\":0}", NULL},
    {"start_confirm", "start_confirm", "{\"label\":\"Bomb\",\"timer_s\":600}", NULL},
    {"wifi_setup", "wifi_setup", "{\"ssid\":\"atalaia-3F2A\"}", NULL},
    /* Declarative templates (ADR-P3-4): Bomb and Domination migrated, the phase 3 modes. */
    {"yaml_bomb_standby", "standby", "{\"arm\":\"red\"}", BOMB},
    {"yaml_bomb_countdown", "countdown", "{\"left\":299}", BOMB},
    {"yaml_bomb_countdown_last_seconds", "countdown", "{\"left\":7,\"team\":\"red\"}", BOMB},
    {"yaml_bomb_defused", "defused", "{\"team\":\"blue\"}", BOMB},
    {"yaml_bomb_defused_yellow", "defused", "{\"team\":\"yellow\"}", BOMB},
    {"yaml_bomb_exploded", "exploded", "{\"team\":\"red\"}", BOMB},
    {"yaml_domination_standby", "standby", "{}", DOM},
    {"yaml_domination_captured", "captured", "{\"team\":\"red\",\"points\":12,\"since\":95}", DOM},
    {"yaml_domination_final_score", "final_score", "{\"owner\":\"blue\",\"points\":40}", DOM},
    {"yaml_domination_final_score_no_owner", "final_score", "{}", DOM},
    {"yaml_kill_confirmed", "tags", "{\"error\":false}", KILL},
    {"yaml_kill_confirmed_open", "tags",
     "{\"team\":\"red\",\"left\":14,\"message\":\"Kill confirmed: b1\",\"error\":false}", KILL},
    {"yaml_kill_confirmed_forged", "tags", "{\"message\":\"Forged tag\",\"error\":true}", KILL},
    {"yaml_respawn", "respawn",
     "{\"team\":\"blue\",\"player\":\"b3\",\"lives\":17,\"message\":\"Back in the game\","
     "\"error\":false}",
     RESPAWN},
    {"yaml_respawn_out", "respawn",
     "{\"team\":\"red\",\"player\":\"r1\",\"lives\":0,\"message\":\"No lives left: team out\","
     "\"error\":true}",
     RESPAWN},
    {"yaml_checkin", "checkin",
     "{\"total\":5,\"counts\":\"RED 3  BLUE 2\",\"team\":\"red\",\"message\":\"Checked in: r2\","
     "\"error\":false}",
     CHECKIN},
    /* The Medic Kit: Portuguese by default (accents folded for the ASCII fonts), and English. */
    {"yaml_medic_idle", "medic_idle", "{\"remaining\":4}", MEDIC},
    {"yaml_medic_idle_team_one_left", "medic_idle", "{\"remaining\":1,\"team\":\"blue\"}", MEDIC},
    {"yaml_medic_hold", "medic_hold",
     "{\"player\":\"b1\",\"team\":\"blue\",\"progress\":0.6,\"left\":4,\"remaining\":4}", MEDIC},
    {"yaml_medic_healed", "medic_healed",
     "{\"player\":\"b1\",\"team\":\"blue\",\"remaining\":3,\"used\":1,\"max\":2}", MEDIC},
    {"yaml_medic_refused", "medic_refused",
     "{\"reason\":\"limit\",\"message\":\"Chegaste ao limite de tratamentos\",\"player\":\"r2\","
     "\"team\":\"red\",\"remaining\":3}",
     MEDIC},
    {"yaml_medic_empty", "medic_empty", "{}", MEDIC},
    {"yaml_medic_hold_en", "medic_hold",
     "{\"player\":\"b1\",\"team\":\"blue\",\"progress\":0.25,\"left\":8,\"remaining\":4}",
     MEDIC_EN},
};
#define CASE_COUNT ((int)(sizeof(cases) / sizeof(cases[0])))

static int failures;

static uint8_t rendered[W * H * 3];

static void fail(const char *name, const char *msg)
{
    fprintf(stderr, "FAIL screen %s: %s\n", name, msg);
    failures++;
}

/* Every visible widget must lie inside the screen and inside its parent. */
static void check_bounds(const char *name, lv_obj_t *obj, const lv_area_t *outer)
{
    uint32_t n = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *child = lv_obj_get_child(obj, (int32_t)i);
        if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
        lv_area_t a;
        lv_obj_get_coords(child, &a);
        if (a.x1 < outer->x1 || a.y1 < outer->y1 || a.x2 > outer->x2 || a.y2 > outer->y2) {
            char msg[160];
            snprintf(msg, sizeof(msg),
                     "a widget at (%d,%d)-(%d,%d) is outside (%d,%d)-(%d,%d), so it is clipped",
                     (int)a.x1, (int)a.y1, (int)a.x2, (int)a.y2, (int)outer->x1, (int)outer->y1,
                     (int)outer->x2, (int)outer->y2);
            fail(name, msg);
        }
        check_bounds(name, child, &a);
    }
}

/* No two visible labels may overlap: text drawn over text is never intended. */
#define LABELS_MAX 64
static int collect_labels(lv_obj_t *obj, lv_area_t *out, int n)
{
    uint32_t count = lv_obj_get_child_count(obj);
    for (uint32_t i = 0; i < count && n < LABELS_MAX; i++) {
        lv_obj_t *child = lv_obj_get_child(obj, (int32_t)i);
        if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
        if (lv_obj_check_type(child, &lv_label_class) && lv_label_get_text(child)[0]) {
            lv_obj_get_coords(child, &out[n++]);
        }
        n = collect_labels(child, out, n);
    }
    return n;
}

static void check_overlaps(const char *name)
{
    lv_area_t a[LABELS_MAX];
    int n = collect_labels(lv_screen_active(), a, 0);
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            if (a[i].x1 <= a[j].x2 && a[j].x1 <= a[i].x2 && a[i].y1 <= a[j].y2 &&
                a[j].y1 <= a[i].y2) {
                char msg[160];
                snprintf(msg, sizeof(msg), "labels at (%d,%d)-(%d,%d) and (%d,%d)-(%d,%d) overlap",
                         (int)a[i].x1, (int)a[i].y1, (int)a[i].x2, (int)a[i].y2, (int)a[j].x1,
                         (int)a[j].y1, (int)a[j].x2, (int)a[j].y2);
                fail(name, msg);
            }
        }
    }
}

static void render(const screen_case_t *c)
{
    if (c->mode) screen_render(SCREEN_MODE_MESSAGE, c->mode);
    if (!screen_render(c->template_name, c->data)) fail(c->name, "template not recognised");
    if (c->mode && !screen_template_widget_count()) fail(c->name, "not drawn from its template");
    test_display_render();
    test_display_rgb888(rendered);
}

static bool update_mode(void)
{
    const char *v = getenv("ATALAIA_UPDATE_SCREENS");
    return v && v[0] && strcmp(v, "0") != 0;
}

static void compare_with_reference(const screen_case_t *c)
{
    char path[512];
    snprintf(path, sizeof(path), "%s/%s.png", SCREENS_OUT_DIR, c->name);
    if (!png_write_rgb(path, W, H, rendered)) fail(c->name, "cannot write the rendered PNG");

    snprintf(path, sizeof(path), "%s/%s.png", SCREENS_REF_DIR, c->name);
    if (update_mode()) {
        if (!png_write_rgb(path, W, H, rendered)) fail(c->name, "cannot update the reference");
        printf("updated %s\n", path);
        return;
    }

    int rw = 0, rh = 0;
    uint8_t *ref = png_read_rgb(path, &rw, &rh);
    if (!ref) {
        fail(c->name, "no reference PNG; run with ATALAIA_UPDATE_SCREENS=1 to create it");
        return;
    }
    if (rw != W || rh != H) {
        fail(c->name, "the reference PNG is not 320x240");
        png_free(ref);
        return;
    }

    int diff = 0, x1 = W, y1 = H, x2 = -1, y2 = -1;
    static uint8_t diff_img[W * H * 3];
    for (int i = 0; i < W * H; i++) {
        bool same = memcmp(&rendered[3 * i], &ref[3 * i], 3) == 0;
        for (int k = 0; k < 3; k++) {
            diff_img[3 * i + k] = same ? (uint8_t)(rendered[3 * i + k] / 4) : (k == 1 ? 0 : 255);
        }
        if (same) continue;
        diff++;
        int x = i % W, y = i / W;
        if (x < x1) x1 = x;
        if (y < y1) y1 = y;
        if (x > x2) x2 = x;
        if (y > y2) y2 = y;
    }
    png_free(ref);
    if (diff) {
        snprintf(path, sizeof(path), "%s/%s.diff.png", SCREENS_OUT_DIR, c->name);
        png_write_rgb(path, W, H, diff_img);
        fprintf(stderr,
                "  %d pixels differ in (%d,%d)-(%d,%d)\n  rendered: %s/%s.png\n  diff: %s\n", diff,
                x1, y1, x2, y2, SCREENS_OUT_DIR, c->name, path);
        fail(c->name, "differs from its reference; if intended, run with ATALAIA_UPDATE_SCREENS=1");
    }
}

/* Every reference PNG must belong to a case, so stale images do not linger. */
static void check_no_stale_references(void)
{
    DIR *dir = opendir(SCREENS_REF_DIR);
    if (!dir) {
        fail("(all)", "cannot open the reference folder " SCREENS_REF_DIR);
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
        if (!known) fail(e->d_name, "reference PNG without a test case; delete it or add a case");
    }
    closedir(dir);
}

/* Patching a shown template must give the same pixels as building it afresh. */
static void check_patch_matches_build(void)
{
    static uint8_t patched[W * H * 3];
    screen_renderer_reset();
    screen_render("countdown", "{\"left\":299}");
    test_display_render();
    screen_render("countdown", "{\"left\":7}");
    test_display_render();
    test_display_rgb888(patched);

    screen_renderer_reset();
    screen_render("countdown", "{\"left\":7}");
    test_display_render();
    test_display_rgb888(rendered);
    if (memcmp(patched, rendered, sizeof(rendered)) != 0) {
        fail("countdown", "patching 299 -> 7 differs from building the screen at 7");
    }

    /* The same for a declarative template, through the colour change at 10 s. */
    screen_renderer_reset();
    screen_render(SCREEN_MODE_MESSAGE, BOMB);
    screen_render("countdown", "{\"left\":299}");
    test_display_render();
    screen_render("countdown", "{\"left\":7,\"team\":\"red\"}");
    test_display_render();
    test_display_rgb888(patched);
    screen_renderer_reset();
    screen_render(SCREEN_MODE_MESSAGE, BOMB);
    screen_render("countdown", "{\"left\":7,\"team\":\"red\"}");
    test_display_render();
    test_display_rgb888(rendered);
    if (memcmp(patched, rendered, sizeof(rendered)) != 0) {
        fail("yaml_bomb_countdown", "patching 299 -> 7 differs from building the screen at 7");
    }
}

int main(void)
{
    mkdir(SCREENS_OUT_DIR, 0755);
    test_display_init();

    for (int i = 0; i < CASE_COUNT; i++) {
        /* Start each case from an empty screen, as after a template change. */
        screen_renderer_reset();
        render(&cases[i]);
        lv_area_t screen = {0, 0, W - 1, H - 1};
        check_bounds(cases[i].name, lv_screen_active(), &screen);
        check_overlaps(cases[i].name);
        compare_with_reference(&cases[i]);
    }
    check_patch_matches_build();
    if (!update_mode()) check_no_stale_references();

    if (failures) {
        fprintf(stderr, "screens: %d failure(s)\n", failures);
        return 1;
    }
    printf("screens: %d renders match their reference images (%s)\n", CASE_COUNT, SCREENS_OUT_DIR);
    return 0;
}
