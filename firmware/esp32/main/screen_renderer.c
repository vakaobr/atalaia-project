/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Screen renderer implementation.
 *
 * All builds: records template name and data for test inspection.
 * ESP32 builds (ATALAIA_SCREEN_LVGL): also creates LVGL widget trees
 * on the active screen. The LVGL path is compiled on ESP32 only;
 * template routing and data passing are tested on the host.
 */
#include "screen_renderer.h"

#include <stdio.h>
#include <string.h>

static char last_template[SCREEN_TEMPLATE_MAX];
static char last_data[SCREEN_DATA_MAX];
static int call_count;

/* Known templates. */
static const char *known_templates[] = {
    "standby", "countdown", "defused",       "exploded",   "final_score",
    "paused",  "status",    "preset_select", "wifi_setup", NULL,
};

/* ------------------------------------------------------------------ */
/* LVGL rendering (ESP32 only)                                         */
/* ------------------------------------------------------------------ */

#if ATALAIA_SCREEN_LVGL

#include "lvgl.h"

/*
 * Simple JSON string extraction: finds "key":"value" and copies value
 * into out. Returns false if the key is not found.
 */
static bool json_extract_str(const char *json, const char *key, char *out, size_t out_sz)
{
    if (!json || !key || !out || out_sz == 0) return false;
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\":\"", key);
    const char *start = strstr(json, pattern);
    if (!start) return false;
    start += strlen(pattern);
    const char *end = strchr(start, '"');
    if (!end) return false;
    size_t len = (size_t)(end - start);
    if (len >= out_sz) len = out_sz - 1;
    memcpy(out, start, len);
    out[len] = '\0';
    return true;
}

/*
 * Simple JSON integer extraction: finds "key":123 and returns the value.
 * Returns def if the key is not found.
 */
static int json_extract_int(const char *json, const char *key, int def)
{
    if (!json || !key) return def;
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    const char *start = strstr(json, pattern);
    if (!start) return def;
    start += strlen(pattern);
    /* Skip whitespace. */
    while (*start == ' ') start++;
    if (*start < '0' || *start > '9') return def;
    return atoi(start);
}

static void screen_render_standby(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "STANDBY");
    lv_obj_align(title, LV_ALIGN_CENTER, 0, -20);

    char arm[SCREEN_TEMPLATE_MAX] = "";
    if (json_extract_str(data_json, "arm", arm, sizeof(arm))) {
        lv_obj_t *team_lbl = lv_label_create(scr);
        lv_label_set_text(team_lbl, arm);
        lv_obj_align(team_lbl, LV_ALIGN_CENTER, 0, 10);
    }
}

static void screen_render_countdown(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    int left = json_extract_int(data_json, "left", 0);
    char buf[16];
    snprintf(buf, sizeof(buf), "%d", left);

    lv_obj_t *timer_lbl = lv_label_create(scr);
    lv_label_set_text(timer_lbl, buf);
    lv_obj_set_style_text_font(timer_lbl, &lv_font_montserrat_28, 0);
    lv_obj_align(timer_lbl, LV_ALIGN_CENTER, 0, -10);

    char team[SCREEN_TEMPLATE_MAX] = "";
    if (json_extract_str(data_json, "team", team, sizeof(team))) {
        lv_obj_t *team_lbl = lv_label_create(scr);
        lv_label_set_text(team_lbl, team);
        lv_obj_align(team_lbl, LV_ALIGN_CENTER, 0, 20);
    }
}

static void screen_render_defused(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "DEFUSED");
    lv_obj_align(title, LV_ALIGN_CENTER, 0, -20);

    char team[SCREEN_TEMPLATE_MAX] = "";
    if (json_extract_str(data_json, "team", team, sizeof(team))) {
        lv_obj_t *team_lbl = lv_label_create(scr);
        lv_label_set_text(team_lbl, team);
        lv_obj_align(team_lbl, LV_ALIGN_CENTER, 0, 10);
    }
}

static void screen_render_exploded(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "EXPLODED");
    lv_obj_align(title, LV_ALIGN_CENTER, 0, -20);

    char team[SCREEN_TEMPLATE_MAX] = "";
    if (json_extract_str(data_json, "team", team, sizeof(team))) {
        lv_obj_t *team_lbl = lv_label_create(scr);
        lv_label_set_text(team_lbl, team);
        lv_obj_align(team_lbl, LV_ALIGN_CENTER, 0, 10);
    }
}

static void screen_render_final_score(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "FINAL SCORE");
    lv_obj_align(title, LV_ALIGN_CENTER, 0, -20);

    char owner[SCREEN_TEMPLATE_MAX] = "";
    if (json_extract_str(data_json, "owner", owner, sizeof(owner))) {
        lv_obj_t *owner_lbl = lv_label_create(scr);
        lv_label_set_text(owner_lbl, owner);
        lv_obj_align(owner_lbl, LV_ALIGN_CENTER, 0, 10);
    }
}

static void screen_render_paused(const char *data_json)
{
    (void)data_json;
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "PAUSED");
    lv_obj_align(title, LV_ALIGN_CENTER, 0, 0);
}

static void screen_render_status(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "STATUS");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 5);

    int battery = json_extract_int(data_json, "battery", -1);
    if (battery >= 0) {
        char buf[32];
        snprintf(buf, sizeof(buf), "Battery: %d%%", battery);
        lv_obj_t *bat_lbl = lv_label_create(scr);
        lv_label_set_text(bat_lbl, buf);
        lv_obj_align(bat_lbl, LV_ALIGN_CENTER, 0, -10);
    }

    char version[32] = "";
    if (json_extract_str(data_json, "version", version, sizeof(version))) {
        char buf[48];
        snprintf(buf, sizeof(buf), "v%s", version);
        lv_obj_t *ver_lbl = lv_label_create(scr);
        lv_label_set_text(ver_lbl, buf);
        lv_obj_align(ver_lbl, LV_ALIGN_CENTER, 0, 10);
    }
}

static void screen_render_preset_select(const char *data_json)
{
    (void)data_json;
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "SELECT PRESET");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 5);

    /* TODO: parse presets array and create a list widget. */
}

static void screen_render_wifi_setup(const char *data_json)
{
    lv_obj_clean(lv_screen_active());
    lv_obj_t *scr = lv_screen_active();

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "WI-FI SETUP");
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 5);

    char ssid[48] = "";
    if (json_extract_str(data_json, "ssid", ssid, sizeof(ssid))) {
        char buf[80];
        snprintf(buf, sizeof(buf), "Connect to:\n%s", ssid);
        lv_obj_t *info = lv_label_create(scr);
        lv_label_set_text(info, buf);
        lv_obj_align(info, LV_ALIGN_CENTER, 0, 0);
    }
}

static void lvgl_render(const char *template_name, const char *data_json)
{
    if (strcmp(template_name, "standby") == 0)
        screen_render_standby(data_json);
    else if (strcmp(template_name, "countdown") == 0)
        screen_render_countdown(data_json);
    else if (strcmp(template_name, "defused") == 0)
        screen_render_defused(data_json);
    else if (strcmp(template_name, "exploded") == 0)
        screen_render_exploded(data_json);
    else if (strcmp(template_name, "final_score") == 0)
        screen_render_final_score(data_json);
    else if (strcmp(template_name, "paused") == 0)
        screen_render_paused(data_json);
    else if (strcmp(template_name, "status") == 0)
        screen_render_status(data_json);
    else if (strcmp(template_name, "preset_select") == 0)
        screen_render_preset_select(data_json);
    else if (strcmp(template_name, "wifi_setup") == 0)
        screen_render_wifi_setup(data_json);
}

#endif /* ATALAIA_SCREEN_LVGL */

/* ------------------------------------------------------------------ */
/* Public API                                                          */
/* ------------------------------------------------------------------ */

bool screen_render(const char *template_name, const char *data_json)
{
    if (!template_name) return false;

    /* Check if this is a known template. */
    bool found = false;
    for (int i = 0; known_templates[i]; i++) {
        if (strcmp(template_name, known_templates[i]) == 0) {
            found = true;
            break;
        }
    }
    if (!found) return false;

    /* Record for test inspection (all builds). */
    snprintf(last_template, sizeof(last_template), "%s", template_name);
    if (data_json) {
        snprintf(last_data, sizeof(last_data), "%s", data_json);
    } else {
        last_data[0] = '\0';
    }
    call_count++;

#if ATALAIA_SCREEN_LVGL
    lvgl_render(template_name, data_json);
#endif

    return true;
}

void screen_renderer_reset(void)
{
    last_template[0] = '\0';
    last_data[0] = '\0';
    call_count = 0;
}

const char *screen_renderer_last_template(void)
{
    return last_template;
}

const char *screen_renderer_last_data(void)
{
    return last_data;
}

int screen_renderer_call_count(void)
{
    return call_count;
}
