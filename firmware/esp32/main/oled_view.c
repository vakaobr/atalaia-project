/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The on-board OLED's status view (oled_view.h): 128x64, a 16-pixel
 * header bar (Montserrat 14, dark on lit), a 32-pixel middle line
 * (Montserrat 28, smaller when the text does not fit) and a 16-pixel
 * footer (Montserrat 14).
 */
#include "oled_view.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

#include "box_text.h"
#include "screen_json.h"
#include "screen_types.h"

/* ---- Mapping (plain C) ------------------------------------------------- */

#define PIN_MAX_DOTS 8
/* The box's own hold bar fills in the steps a mode's would: one per hold event. */
#define HOLD_STEP_MS 250

static void upper(char *s)
{
    for (; *s; s++) {
        *s = *s == '_' ? ' ' : (char)toupper((unsigned char)*s);
    }
}

static void set(char *dst, size_t sz, const char *src)
{
    snprintf(dst, sz, "%s", src ? src : "");
}

static void set_text(char *dst, size_t sz, box_text_id_t id)
{
    set(dst, sz, box_text(id));
}

/* 299 -> "4:59", 3725 -> "1:02:05". */
static void clock_text(long s, char *out, size_t sz)
{
    if (s < 0) s = 0;
    if (s >= 3600) {
        snprintf(out, sz, "%ld:%02ld:%02ld", s / 3600, (s / 60) % 60, s % 60);
    } else {
        snprintf(out, sz, "%ld:%02ld", s / 60, s % 60);
    }
}

/* n masked digits, "* * * *"; "- - - -" for none. */
static void dots(long n, char *out, size_t sz)
{
    if (n < 0) n = 0;
    if (n > PIN_MAX_DOTS) n = PIN_MAX_DOTS;
    size_t len = 0;
    out[0] = '\0';
    long shown = n ? n : 4;
    for (long i = 0; i < shown && len + 2 < sz; i++) {
        if (i) out[len++] = ' ';
        out[len++] = n ? '*' : '-';
    }
    out[len] = '\0';
}

/* The value of the first of keys that holds a non-empty string. */
static bool first_str(const char *data, const char *const *keys, char *out, size_t sz)
{
    for (; *keys; keys++) {
        if (screen_json_str(data, *keys, out, sz) && out[0]) return true;
    }
    out[0] = '\0';
    return false;
}

void oled_mode_title(const char *mode_msg, char *out, size_t out_sz)
{
    if (!out_sz) return;
    out[0] = '\0';
    if (!mode_msg) return;
    /* The mode id runs to the first space; its last dotted part names it. */
    size_t len = strcspn(mode_msg, " ");
    const char *name = mode_msg;
    for (size_t i = 0; i < len; i++) {
        if (mode_msg[i] == '.') name = mode_msg + i + 1;
    }
    size_t n = (size_t)(mode_msg + len - name);
    if (n >= out_sz) n = out_sz - 1;
    memcpy(out, name, n);
    out[n] = '\0';
    upper(out);
}

uint32_t oled_mode_hold_ms(const char *mode_msg)
{
    const char *params = mode_msg ? strchr(mode_msg, ' ') : NULL;
    long v;
    if (!params) return 0;
    if (screen_json_int(params + 1, "capture_hold_ms", &v) && v > 0) return (uint32_t)v;
    if (screen_json_int(params + 1, "hold_ms", &v) && v > 0) return (uint32_t)v;
    return 0;
}

/* A 0-1 share in data as 0-100, or -1 when the key is absent or 0. */
static int share_pct(const char *data, const char *key)
{
    double v;
    if (!screen_json_number(data, key, &v) || v <= 0) return -1;
    return v >= 1 ? 100 : (int)(v * 100);
}

bool oled_text_for(const char *mode_title, const char *t, const char *data, oled_text_t *out)
{
    memset(out, 0, sizeof(*out));
    out->bar = -1;
    out->since = -1;
    if (!t || strcmp(t, "@mode") == 0) return false;
    if (!data) data = "{}";
    const char *mode = mode_title && mode_title[0] ? mode_title : "ATALAIA";
    /* A built-in mode's name in the box's language; a package's stays as its id says. */
    const char *named = box_text_mode_name(mode);
    if (named) mode = named;

    char s[32];
    long v = 0;

    /* ---- the shell's screens ---- */
    if (strcmp(t, "pin_entry") == 0) {
        set_text(out->head, sizeof(out->head), TXO_ADMIN_PIN);
        screen_json_int(data, "digits", &v);
        dots(v, out->big, sizeof(out->big));
        set_text(out->foot, sizeof(out->foot),
                 screen_json_true(data, "error") ? TXO_WRONG_PIN : TXO_ENTER_DELETE);
        /* The wait after wrong PINs, or no PIN set (decisions AD-28, AD-29). */
        long wait_min = 0;
        if (screen_json_true(data, "no_pin")) {
            set_text(out->big, sizeof(out->big), TXO_NO_PIN);
            set_text(out->foot, sizeof(out->foot), TXO_SET_PIN);
        } else if (screen_json_int(data, "locked_min", &wait_min) && wait_min > 0) {
            set_text(out->big, sizeof(out->big), TXO_PIN_LOCKED);
            snprintf(out->foot, sizeof(out->foot), box_text(TXO_AGAIN_IN_MIN),
                     (unsigned long)wait_min);
        }
        return true;
    }
    if (strcmp(t, "preset_select") == 0) {
        char names[9][32];
        int count = screen_json_str_list(data, "presets", names[0], sizeof(names[0]), 9);
        long selected = 1, page = 1, pages = 1;
        screen_json_int(data, "selected", &selected);
        screen_json_int(data, "page", &page);
        screen_json_int(data, "pages", &pages);
        set_text(out->head, sizeof(out->head), TXO_GAMES);
        if (pages > 1) snprintf(out->head_right, sizeof(out->head_right), "%ld/%ld", page, pages);
        if (selected >= 1 && selected <= count) {
            snprintf(out->big, sizeof(out->big), "%d %s", (int)selected, names[selected - 1]);
        } else {
            set(out->big, sizeof(out->big), count ? "-" : box_text(TXO_NO_GAMES));
        }
        set_text(out->foot, sizeof(out->foot), pages > 1 ? TXO_PICK_PAGES : TXO_PICK);
        return true;
    }
    if (strcmp(t, "timer_adjust") == 0) {
        set_text(out->head, sizeof(out->head), TXO_GAME_TIME);
        screen_json_int(data, "timer_s", &v);
        clock_text(v, out->big, sizeof(out->big));
        set_text(out->foot, sizeof(out->foot), TXO_TIMER_KEYS);
        return true;
    }
    if (strcmp(t, "start_confirm") == 0) {
        if (screen_json_true(data, "setup")) { /* the picker's "Wi-Fi setup" entry asks first */
            set_text(out->head, sizeof(out->head), TXO_WIFI_SETUP);
            set_text(out->big, sizeof(out->big), TXO_SETUP_Q);
            set_text(out->foot, sizeof(out->foot), TXO_KEYS_SETUP);
            return true;
        }
        set_text(out->head, sizeof(out->head), TXO_START_Q);
        if (screen_json_str(data, "label", s, sizeof(s)) && s[0]) {
            set(out->big, sizeof(out->big), s);
        }
        if (screen_json_int(data, "timer_s", &v)) {
            clock_text(v, out->head_right, sizeof(out->head_right));
        }
        set_text(out->foot, sizeof(out->foot), TXO_START_BACK);
        return true;
    }
    if (strcmp(t, "status") == 0) {
        if (!screen_json_str(data, "title", s, sizeof(s)) || !s[0]) {
            set_text(s, sizeof(s), TX_STATUS_UP);
        }
        upper(s);
        set(out->head, sizeof(out->head), s);
        if (screen_json_str(data, "code", s, sizeof(s)) && s[0]) {
            set(out->big, sizeof(out->big), s); /* pairing: the code to type in the console */
            char id[8];
            if (screen_json_str(data, "id", id, sizeof(id)) && id[0]) {
                snprintf(out->foot, sizeof(out->foot), "id %s  console", id);
            } else {
                set_text(out->foot, sizeof(out->foot), TXO_CONSOLE_ADOPT);
            }
        } else if (screen_json_str(data, "pairing", s, sizeof(s)) && s[0]) {
            set(out->foot, sizeof(out->foot), s); /* pairing paused or locked */
        } else if (screen_json_str(data, "mode", s, sizeof(s)) && s[0]) {
            set(out->big, sizeof(out->big), s);
        } else if (screen_json_str(data, "field", s, sizeof(s)) && s[0]) {
            set(out->big, sizeof(out->big), s); /* adoption: the field, its fingerprint below */
            if (screen_json_str(data, "fingerprint", s, sizeof(s)) && s[0]) {
                set(out->foot, sizeof(out->foot), s);
            }
        }
        if (screen_json_int(data, "timer_s", &v)) clock_text(v, out->foot, sizeof(out->foot));
        return true;
    }
    if (strcmp(t, "wifi_setup") == 0) {
        set_text(out->head, sizeof(out->head), TXO_WIFI_SETUP);
        if (!screen_json_str(data, "ssid", s, sizeof(s)) || !s[0])
            set(s, sizeof(s), "atalaia-....");
        set(out->big, sizeof(out->big), s);
        set_text(out->foot, sizeof(out->foot), TXO_OPEN_PORTAL);
        return true;
    }
    /* A free box, ready for the next game (BN-10); joined, not started yet (BN-12). */
    if (strcmp(t, "ready") == 0) {
        set_text(out->head, sizeof(out->head), TX_READY_UP);
        set_text(out->big, sizeof(out->big), TX_NEXT_GAME);
        if (screen_json_true(data, "picker"))
            set_text(out->foot, sizeof(out->foot), TXO_KEY_PICKER);
        return true;
    }
    if (strcmp(t, "waiting") == 0) {
        set_text(out->head, sizeof(out->head), TX_WAITING_UP);
        screen_json_int(data, "game", &v);
        snprintf(out->big, sizeof(out->big), box_text(TX_GAME_N), (unsigned)v);
        set_text(out->foot, sizeof(out->foot), TXO_NOT_STARTED);
        return true;
    }

    /* ---- mode screens: the mode in the header ---- */
    set(out->head, sizeof(out->head), mode);
    if (strcmp(t, "standby") == 0) {
        set_text(out->big, sizeof(out->big), TX_READY_UP);
        out->bar = share_pct(data, "progress");
        if (out->bar >= 0) {
            set_text(out->foot, sizeof(out->foot), TXO_ARMING);
        } else if (screen_json_str(data, "arm", s, sizeof(s)) && s[0]) {
            upper(s);
            snprintf(out->foot, sizeof(out->foot), box_text(TXO_HOLD_TO_ARM), s);
        } else {
            set_text(out->foot, sizeof(out->foot), TX_WAITING);
        }
        return true;
    }
    /* A zone nobody holds, a zone a team holds (BN-11): never the Bomb's words. While a team
     * holds its button to take it: the bar, and that team ("taker") below (BN-25). */
    if (strcmp(t, "neutral") == 0) {
        out->zone = true;
        set_text(out->big, sizeof(out->big), TX_NEUTRAL_UP);
        out->bar = share_pct(data, "progress");
        set_text(out->foot, sizeof(out->foot), TXO_HOLD_TO_CAPTURE);
        if (out->bar >= 0 && screen_json_str(data, "taker", s, sizeof(s)) && s[0]) {
            upper(s);
            set(out->foot, sizeof(out->foot), s);
        }
        return true;
    }
    /* The team, its points on this box at the right of the header, and how long it has held
     * the zone below (oled_text_held, from the game's clock) when the mode gives them. */
    if (strcmp(t, "captured") == 0 && screen_json_str(data, "team", s, sizeof(s)) && s[0]) {
        out->zone = true;
        set(out->owner, sizeof(out->owner), s);
        upper(s);
        set(out->big, sizeof(out->big), s);
        out->bar = share_pct(data, "progress");
        set_text(out->foot, sizeof(out->foot), TX_ZONE_HELD_UP);
        if (screen_json_int(data, "points", &v)) {
            snprintf(out->head_right, sizeof(out->head_right), box_text(TXO_POINTS), v);
        }
        if (screen_json_int(data, "since", &v) && v >= 0) out->since = v;
        if (out->bar >= 0 && screen_json_str(data, "taker", s, sizeof(s)) && s[0]) {
            upper(s);
            set(out->foot, sizeof(out->foot), s);
        }
        return true;
    }
    if (strcmp(t, "playing") == 0) {
        set_text(out->big, sizeof(out->big), TX_GAME_ON_UP);
        if (screen_json_str(data, "role", s, sizeof(s))) set(out->foot, sizeof(out->foot), s);
        return true;
    }
    if (strcmp(t, "paused") == 0) {
        set_text(out->big, sizeof(out->big), TX_PAUSED_UP);
        set_text(out->foot, sizeof(out->foot), TXO_WAIT_GM);
        return true;
    }
    if (strcmp(t, "code_entry") == 0) {
        if (screen_json_str(data, "title", s, sizeof(s)) && s[0]) {
            upper(s);
            set(out->head, sizeof(out->head), box_text_title(s));
        }
        screen_json_int(data, "digits", &v);
        dots(v, out->big, sizeof(out->big));
        if (screen_json_int(data, "left", &v))
            clock_text(v, out->head_right, sizeof(out->head_right));
        static const char *const msg_keys[] = {"message", NULL};
        first_str(data, msg_keys, out->foot, sizeof(out->foot));
        return true;
    }

    /* Everything else, the modes' own templates included: a countdown when
     * there is one, else the screen's name; a team, owner or message below. */
    if (screen_json_int(data, "left", &v)) {
        clock_text(v, out->big, sizeof(out->big));
    } else if (strcmp(t, "final_score") == 0) {
        set_text(out->big, sizeof(out->big), TX_GAME_OVER_UP);
    } else {
        /* A built-in template's name in the box's language (DESARMADA, not DEFUSED); any other
         * as its name says. */
        const char *named_t = box_text_screen_name(t);
        set(out->big, sizeof(out->big), named_t ? named_t : t);
        if (!named_t) upper(out->big);
    }
    out->bar = share_pct(data, strcmp(t, "countdown") == 0 ? "defuse" : "progress");
    if (out->bar >= 0 && strcmp(t, "countdown") == 0) {
        set_text(out->foot, sizeof(out->foot), TXO_DEFUSE);
        return true;
    }
    static const char *const team_keys[] = {"team", "owner", "winner", NULL};
    static const char *const text_keys[] = {"message", "title", "label", NULL};
    if (first_str(data, team_keys, s, sizeof(s))) {
        upper(s);
        set(out->foot, sizeof(out->foot), s);
    } else if (strcmp(t, "countdown") == 0) {
        set_text(out->foot, sizeof(out->foot), TX_UNTIL_DETONATION);
    } else {
        first_str(data, text_keys, out->foot, sizeof(out->foot));
    }
    return true;
}

bool oled_text_held(oled_text_t *t, long game_s)
{
    if (t->since < 0 || t->bar >= 0) return false;
    char clock[16], foot[sizeof(t->foot)];
    clock_text(game_s - t->since, clock, sizeof(clock));
    snprintf(foot, sizeof(foot), box_text(TXO_HELD_FOR), clock);
    if (strcmp(foot, t->foot) == 0) return false;
    set(t->foot, sizeof(t->foot), foot);
    return true;
}

bool oled_text_hold(oled_text_t *t, const oled_hold_t *holds, int n, uint32_t hold_ms)
{
    if (!t->zone || t->bar >= 0 || hold_ms == 0 || !holds) return false;
    const oled_hold_t *taker = NULL;
    for (int i = 0; i < n; i++) {
        if (!holds[i].team[0] || strcasecmp(holds[i].team, t->owner) == 0) continue;
        if (!taker || holds[i].ms > taker->ms) taker = &holds[i];
    }
    if (!taker) return false;
    uint32_t ms = taker->ms - taker->ms % HOLD_STEP_MS;
    t->bar = ms >= hold_ms ? 100 : (int)((uint64_t)ms * 100u / hold_ms);
    set(t->foot, sizeof(t->foot), taker->team);
    upper(t->foot);
    return true;
}

/* "g" and at least 4 hex digits: the commit of FV-3's build metadata ("gabc1234"). */
static bool commit_id(const char *s, size_t n)
{
    if (n < 5 || s[0] != 'g') return false;
    for (size_t i = 1; i < n; i++) {
        if (!isxdigit((unsigned char)s[i])) return false;
    }
    return true;
}

static bool digits_id(const char *s, size_t n)
{
    if (n == 0) return false;
    for (size_t i = 0; i < n; i++) {
        if (!isdigit((unsigned char)s[i])) return false;
    }
    return true;
}

void oled_version_lines(const char *version, char *line1, size_t n1, char *line2, size_t n2)
{
    if (n1) line1[0] = '\0';
    if (n2) line2[0] = '\0';
    if (!version || !version[0]) return;
    const char *plus = strchr(version, '+');
    int core_len = plus ? (int)(plus - version) : (int)strlen(version);
    if (!plus) {
        if (n1) snprintf(line1, n1, "v%.*s", core_len, version);
        return;
    }
    /* The build metadata's identifiers: [<count>.]g<hash>[.dirty] (FV-3), else as it is. */
    const char *meta = plus + 1;
    const char *id[4];
    size_t len[4];
    int ids = 0; /* 4: four or more, never a commit's */
    for (const char *p = meta; ids < 4;) {
        const char *dot = strchr(p, '.');
        id[ids] = p;
        len[ids] = dot ? (size_t)(dot - p) : strlen(p);
        ids++;
        if (!dot) break;
        p = dot + 1;
    }
    int at = 0;
    const char *count = NULL;
    size_t count_len = 0;
    if (ids >= 1 && ids <= 3 && digits_id(id[0], len[0])) {
        count = id[0];
        count_len = len[0];
        at = 1;
    }
    bool ours = ids <= 3 && at < ids && commit_id(id[at], len[at]);
    bool dirty = false;
    if (ours && at + 1 < ids) {
        dirty = len[at + 1] == 5 && strncmp(id[at + 1], "dirty", 5) == 0;
        ours = dirty && at + 2 == ids;
    }
    if (!ours) {
        if (n1) snprintf(line1, n1, "v%.*s", core_len, version);
        if (n2) snprintf(line2, n2, "%s", meta);
        return;
    }
    if (n1) {
        if (count) {
            snprintf(line1, n1, "v%.*s+%.*s", core_len, version, (int)count_len, count);
        } else {
            snprintf(line1, n1, "v%.*s", core_len, version);
        }
    }
    if (n2) snprintf(line2, n2, "%.*s%s", (int)len[at] - 1, id[at] + 1, dirty ? "*" : "");
}

void oled_pack(const uint16_t *rgb565, uint8_t fb[HAL_OLED_FB_SIZE])
{
    memset(fb, 0, HAL_OLED_FB_SIZE);
    for (int y = 0; y < HAL_OLED_HEIGHT; y++) {
        for (int x = 0; x < HAL_OLED_WIDTH; x++) {
            uint16_t c = rgb565[y * HAL_OLED_WIDTH + x];
            /* 5-6-5 bits scaled to 0-63 each, summed: 0-189. */
            unsigned lum = ((c >> 11) & 0x1F) * 2u + ((c >> 5) & 0x3F) + (c & 0x1F) * 2u;
            if (lum >= 95) fb[(y / 8) * HAL_OLED_WIDTH + x] |= (uint8_t)(1u << (y % 8));
        }
    }
}

/* ---- Drawing (LVGL) ---------------------------------------------------- */

#if ATALAIA_SCREEN_LVGL

#include "oled_logo.h"

#define OLED_W   HAL_OLED_WIDTH
#define OLED_H   HAL_OLED_HEIGHT
#define BAR_H    16
#define TEXT_MAX (OLED_W - 4)

#define HOLD_BAR_W 48
#define HOLD_BAR_H 12

static lv_obj_t *bar, *head, *head_right, *big, *foot, *hold_box, *hold_fill;
static bool built;

static char mode_title[32];
static char pending_t[SCREEN_TEMPLATE_MAX];
static char pending_data[SCREEN_DATA_MAX];
static bool pending;
static uint32_t splash_until;
static bool splash_on;
/* The last screen message's lines (base, while base_on) and what the OLED shows of them
 * (drawn): base with the box's own hold bar (BN-26) and the held time (BN-23) applied. */
static oled_text_t base, drawn;
static bool base_on;
static uint32_t (*game_clock)(void);
static int (*hold_reader)(oled_hold_t *holds, int max);
static uint32_t hold_ms; /* the mode's hold time to take a zone ("@mode"); 0 none */

/* One line of text: too long ends in "...", never wraps. */
static lv_obj_t *text(lv_obj_t *parent, const lv_font_t *font, lv_color_t colour)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, colour, 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
    lv_obj_set_height(l, lv_font_get_line_height(font));
    return l;
}

static void clean(lv_obj_t *scr)
{
    lv_obj_clean(scr);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    built = false;
    base_on = false;
}

static void build(lv_obj_t *scr)
{
    clean(scr);
    bar = lv_obj_create(scr);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, OLED_W, BAR_H);
    lv_obj_set_style_bg_color(bar, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);

    head_right = text(bar, &lv_font_atalaia_14, lv_color_black());
    lv_label_set_long_mode(head_right, LV_LABEL_LONG_CLIP);
    lv_obj_align(head_right, LV_ALIGN_RIGHT_MID, -2, 0);
    head = text(bar, &lv_font_atalaia_14, lv_color_black());
    lv_obj_align(head, LV_ALIGN_LEFT_MID, 2, 0);

    big = text(scr, &lv_font_atalaia_28, lv_color_white());
    lv_obj_set_width(big, TEXT_MAX);
    lv_obj_set_style_text_align(big, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(big, LV_ALIGN_CENTER, 0, 0);

    foot = text(scr, &lv_font_atalaia_14, lv_color_white());

    /* A hold's progress: an outlined box filling from the left. */
    hold_box = lv_obj_create(scr);
    lv_obj_remove_style_all(hold_box);
    lv_obj_set_size(hold_box, HOLD_BAR_W, HOLD_BAR_H);
    lv_obj_set_style_border_color(hold_box, lv_color_white(), 0);
    lv_obj_set_style_border_width(hold_box, 1, 0);
    lv_obj_set_style_pad_all(hold_box, 2, 0);
    lv_obj_align(hold_box, LV_ALIGN_BOTTOM_RIGHT, -1, -2);
    hold_fill = lv_obj_create(hold_box);
    lv_obj_remove_style_all(hold_fill);
    lv_obj_set_style_bg_color(hold_fill, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(hold_fill, LV_OPA_COVER, 0);
    lv_obj_set_height(hold_fill, HOLD_BAR_H - 6);
    lv_obj_align(hold_fill, LV_ALIGN_LEFT_MID, 0, 0);
    built = true;
}

static int32_t width_of(const char *s, const lv_font_t *font)
{
    return lv_text_get_width(s, (uint32_t)strlen(s), font, 0);
}

/* The footer: centred text, or text on the left and the hold bar. */
static void draw_foot(const oled_text_t *t)
{
    bool with_bar = t->bar >= 0;
    if (with_bar) {
        lv_obj_set_width(foot, OLED_W - HOLD_BAR_W - 6);
        lv_obj_set_style_text_align(foot, LV_TEXT_ALIGN_LEFT, 0);
        lv_obj_align(foot, LV_ALIGN_BOTTOM_LEFT, 2, 0);
        int inner = HOLD_BAR_W - 6;
        int pct = t->bar > 100 ? 100 : t->bar;
        lv_obj_set_width(hold_fill, inner * pct / 100);
        lv_obj_remove_flag(hold_box, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_set_width(foot, TEXT_MAX);
        lv_obj_set_style_text_align(foot, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(foot, LV_ALIGN_BOTTOM_MID, 0, 0);
        lv_obj_add_flag(hold_box, LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(foot, t->foot);
}

static void draw(lv_obj_t *scr, const oled_text_t *t)
{
    if (!built) build(scr);

    lv_label_set_text(head_right, t->head_right);
    int32_t right_w = t->head_right[0] ? width_of(t->head_right, &lv_font_atalaia_14) + 6 : 0;
    lv_obj_set_width(head, OLED_W - 4 - right_w);
    lv_label_set_text(head, t->head);

    /* The biggest font the middle line fits in. */
    const lv_font_t *font = &lv_font_atalaia_28;
    if (width_of(t->big, font) > TEXT_MAX) font = &lv_font_atalaia_20;
    if (width_of(t->big, font) > TEXT_MAX) font = &lv_font_atalaia_14;
    lv_obj_set_style_text_font(big, font, 0);
    lv_obj_set_height(big, lv_font_get_line_height(font));
    lv_label_set_text(big, t->big);
    lv_obj_align(big, LV_ALIGN_CENTER, 0, 0);
    draw_foot(t);
}

void oled_view_draw(lv_obj_t *scr, const oled_text_t *t)
{
    if (!scr) return;
    draw(scr, t);
    base_on = false; /* drawn from outside: nothing of a screen message's to keep up */
}

void oled_view_splash(lv_obj_t *scr, const char *version, uint32_t now_ms, uint32_t hold_ms)
{
    if (!scr) return;
    clean(scr);

    static lv_image_dsc_t logo;
    logo.header.magic = LV_IMAGE_HEADER_MAGIC;
    logo.header.cf = LV_COLOR_FORMAT_A8;
    logo.header.w = OLED_LOGO_W;
    logo.header.h = OLED_LOGO_H;
    logo.header.stride = OLED_LOGO_W;
    logo.data = oled_logo_a8;
    logo.data_size = sizeof(oled_logo_a8);

    lv_obj_t *img = lv_image_create(scr);
    lv_image_set_src(img, &logo);
    lv_obj_set_style_image_recolor(img, lv_color_white(), 0);
    lv_obj_set_style_image_recolor_opa(img, LV_OPA_COVER, 0);
    lv_obj_align(img, LV_ALIGN_LEFT_MID, OLED_SPLASH_LOGO_X, 0);

    /* The version in two lines (FV-8): a release's one line; a development build's commit on a
     * second, the lines moved up to make room. Past the tower, 92 pixels: "v0.4.0-dev.12" and
     * "0.4.0-dev.123" fit; a longer one ends in "...". */
    char line1[40], line2[24];
    oled_version_lines(version, line1, sizeof(line1), line2, sizeof(line2));
    const int32_t x = OLED_SPLASH_TEXT_X;
    lv_obj_t *name = text(scr, &lv_font_atalaia_20, lv_color_white());
    lv_label_set_text(name, "ATALAIA");
    lv_obj_align(name, LV_ALIGN_LEFT_MID, x, line2[0] ? -16 : -8);

    lv_obj_t *ver = text(scr, &lv_font_atalaia_14, lv_color_white());
    lv_obj_set_width(ver, OLED_W - x);
    lv_label_set_text(ver, oled_version_fit(line1, &lv_font_atalaia_14, OLED_W - x));
    lv_obj_align_to(ver, name, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 2);
    if (line2[0]) {
        lv_obj_t *commit = text(scr, &lv_font_atalaia_14, lv_color_white());
        lv_obj_set_width(commit, OLED_W - x);
        lv_label_set_text(commit, line2);
        lv_obj_align_to(commit, ver, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 0);
    }

    splash_on = true;
    splash_until = now_ms + hold_ms;
}

const char *oled_version_fit(const char *line1, const lv_font_t *font, int32_t max_w)
{
    if (!line1) return "";
    if (line1[0] != 'v') return line1;
    int32_t w = lv_text_get_width(line1, (uint32_t)strlen(line1), font, 0);
    return w <= max_w ? line1 : line1 + 1;
}

void oled_view_set_game_clock(uint32_t (*game_ms)(void))
{
    game_clock = game_ms;
}

void oled_view_set_hold_reader(int (*read)(oled_hold_t *holds, int max))
{
    hold_reader = read;
}

/* base as it shows now: a team holding its button on a zone (the bar and the team), else
 * the held time. Only the footer and the bar differ from base. */
static void compose(oled_text_t *t)
{
    *t = base;
    if (hold_reader && t->zone && t->bar < 0) {
        oled_hold_t holds[OLED_HOLDS_MAX];
        int n = hold_reader(holds, OLED_HOLDS_MAX);
        oled_text_hold(t, holds, n > OLED_HOLDS_MAX ? OLED_HOLDS_MAX : n, hold_ms);
    }
    if (game_clock && t->since >= 0) oled_text_held(t, (long)(game_clock() / 1000u));
}

static void show(lv_obj_t *scr, const char *t, const char *data)
{
    oled_text_t txt;
    if (!oled_text_for(mode_title, t, data, &txt)) return;
    base = txt;
    compose(&txt);
    draw(scr, &txt);
    drawn = txt;
    base_on = true;
}

/* A hold's bar stepping (four times a second at most) or the held time's second: the footer
 * only, one or two of the panel's pages (as a countdown's tick); the TFT is not touched. */
static void refresh(void)
{
    if (!base_on || !built) return;
    oled_text_t t;
    compose(&t);
    if (t.bar == drawn.bar && strcmp(t.foot, drawn.foot) == 0) return;
    draw_foot(&t);
    drawn = t;
}

void oled_view_handle(lv_obj_t *scr, const char *t, const char *data, uint32_t now_ms)
{
    if (!t) return;
    if (strcmp(t, "@mode") == 0) {
        oled_mode_title(data, mode_title, sizeof(mode_title));
        hold_ms = oled_mode_hold_ms(data);
        return;
    }
    if (splash_on && (int32_t)(now_ms - splash_until) < 0) {
        set(pending_t, sizeof(pending_t), t);
        set(pending_data, sizeof(pending_data), data);
        pending = true;
        return;
    }
    splash_on = false;
    pending = false;
    show(scr, t, data);
}

void oled_view_poll(lv_obj_t *scr, uint32_t now_ms)
{
    if (!splash_on) {
        refresh();
        return;
    }
    if ((int32_t)(now_ms - splash_until) < 0) return;
    splash_on = false;
    if (pending) {
        pending = false;
        show(scr, pending_t, pending_data);
    }
}

#endif /* ATALAIA_SCREEN_LVGL */
