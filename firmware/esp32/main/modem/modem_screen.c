/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's on-board OLED (modem_screen.h): a 16-pixel header
 * bar (the tower icon and "MODEM MODE", Montserrat 14, dark on lit) and six
 * 8-pixel lines of unscii 8, 16 characters each; in Chinese the header also
 * holds the link state and the game line is a 16-pixel Montserrat 14 row
 * (modem_screen.h).
 */
#include "modem_screen.h"

#include <stdio.h>
#include <string.h>

/* ---- State and text (plain C) ------------------------------------------- */

void modem_screen_state(const modem_t *m, uint32_t now_ms, uint32_t link_timeout_ms,
                        uint32_t idle_channel_hz, uint32_t duty_ms, const char *fault,
                        modem_screen_state_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!m->host_seen) {
        out->link = MODEM_LINK_WAITING;
    } else {
        out->link = now_ms - m->last_host_ms <= link_timeout_ms ? MODEM_LINK_UP : MODEM_LINK_DOWN;
    }
    out->configured = m->configured;
    out->measuring = m->measuring;
    out->game_id = m->game_id;
    out->channel_hz = m->channel_hz ? m->channel_hz : idle_channel_hz;
    out->rx = m->count.rx_ok;
    out->rx_auth_fail = m->count.rx_auth_fail;
    out->tx = m->count.tx_ok;
    out->tx_fail = m->count.tx_fail;
    out->lang = box_lang_from_code(modem_lang(m));
    out->radio_ok = m->radio_present;
    out->duty_ms = m->radio_present ? duty_ms : 0;
    if (!m->radio_present) {
        snprintf(out->fault, sizeof(out->fault), "%s",
                 fault && fault[0] ? fault : "no SX1262 radio");
    }
}

static int digits(uint32_t n)
{
    int d = 1;
    while (n >= 10) {
        n /= 10;
        d++;
    }
    return d;
}

void modem_screen_count(uint32_t n, int width, char *out, size_t out_sz)
{
    static const char units[] = {'k', 'M', 'G'};
    if (digits(n) <= width) {
        snprintf(out, out_sz, "%lu", (unsigned long)n);
        return;
    }
    uint32_t v = n;
    for (size_t u = 0; u < sizeof(units); u++) {
        v /= 1000u;
        if (digits(v) + 1 <= width || u + 1 == sizeof(units)) {
            snprintf(out, out_sz, "%lu%c", (unsigned long)v, units[u]);
            return;
        }
    }
}

/* left, then right flush with the 16th column; right is cut when both do not fit. */
static void two_col(char *out, const char *left, const char *right)
{
    size_t l = strlen(left);
    if (l > MODEM_SCREEN_COLS) l = MODEM_SCREEN_COLS;
    memset(out, ' ', MODEM_SCREEN_COLS);
    memcpy(out, left, l);
    size_t r = strlen(right);
    size_t room = l < MODEM_SCREEN_COLS ? MODEM_SCREEN_COLS - l - (l ? 1 : 0) : 0;
    if (r > room) r = room;
    memcpy(out + MODEM_SCREEN_COLS - r, right, r);
    /* Trailing spaces off, so the lines compare and test simply. */
    size_t end = MODEM_SCREEN_COLS;
    while (end > 0 && out[end - 1] == ' ') end--;
    out[end] = '\0';
}

/* The first line of s that fits in 16 columns, broken at a space when one
 * is there; returns where the rest starts. */
static const char *wrap(const char *s, char *out)
{
    while (*s == ' ') s++;
    size_t len = strlen(s);
    size_t n = len;
    if (len > MODEM_SCREEN_COLS) {
        n = MODEM_SCREEN_COLS;
        for (size_t i = MODEM_SCREEN_COLS; i > 0; i--) {
            if (s[i] == ' ') {
                n = i;
                break;
            }
        }
    }
    memcpy(out, s, n);
    out[n] = '\0';
    return s + n;
}

/* 869525000 -> "869.525 MHz". */
static void mhz(uint32_t hz, char *out, size_t sz)
{
    snprintf(out, sz, "%lu.%03lu MHz", (unsigned long)(hz / 1000000u),
             (unsigned long)((hz / 1000u) % 1000u));
}

/* 359900 -> "359.9s", 3600000 -> "3600s". */
static void seconds(uint32_t ms, char *out, size_t sz)
{
    if (ms < 1000000u) {
        snprintf(out, sz, "%lu.%lus", (unsigned long)(ms / 1000u),
                 (unsigned long)((ms / 100u) % 10u));
    } else {
        snprintf(out, sz, "%lus", (unsigned long)(ms / 1000u));
    }
}

/* "TX 1234" and "fail 0": the count in 4 characters, the failures in 3. */
static void counts(char *out, const char *label, uint32_t n, const char *bad_label, uint32_t bad)
{
    char a[8], b[8], left[16], right[16];
    modem_screen_count(n, 4, a, sizeof(a));
    modem_screen_count(bad, 3, b, sizeof(b));
    snprintf(left, sizeof(left), "%s %s", label, a);
    snprintf(right, sizeof(right), "%s %s", bad_label, b);
    two_col(out, left, right);
}

static const char *tx(const modem_screen_state_t *s, box_text_id_t id)
{
    return box_text_in(s->lang, id);
}

/* The link's state word. */
static const char *link_word(const modem_screen_state_t *s)
{
    switch (s->link) {
    case MODEM_LINK_UP: return tx(s, TXM_OK);
    case MODEM_LINK_DOWN: return tx(s, TXM_DOWN);
    default: return tx(s, TXM_WAITING);
    }
}

/* The game's state: "GAME" and its id, or "IDLE" and why. */
static void game_texts(const modem_screen_state_t *s, const char **left, char *id, size_t id_sz,
                       const char **right)
{
    if (s->configured) {
        snprintf(id, id_sz, "%u", (unsigned)s->game_id);
        *left = tx(s, TXM_GAME);
        *right = id;
    } else {
        *left = tx(s, TXM_IDLE);
        *right = tx(s, s->measuring ? TXM_MEASURING : TXM_NO_GAME);
    }
}

/* The channel, the counters and the duty budget: 8-pixel lines in every language. */
static void numbers(const modem_screen_state_t *s, modem_screen_text_t *out, int first)
{
    char v[24];
    mhz(s->channel_hz, v, sizeof(v));
    two_col(out->line[first], "CH", v);
    counts(out->line[first + 1], "TX", s->tx, tx(s, TXM_FAIL), s->tx_fail);
    counts(out->line[first + 2], "RX", s->rx, tx(s, TXM_AUTH), s->rx_auth_fail);
    char left[12];
    seconds(s->duty_ms, left, sizeof(left));
    snprintf(v, sizeof(v), tx(s, TXM_LEFT), left);
    two_col(out->line[first + 3], tx(s, TXM_DUTY), v);
    out->inverted[first + 3] = s->duty_ms == 0;
}

/* Chinese: a Han letter needs the 14-pixel font, 16 pixels a row, so the link state goes into the
 * header bar and the game line is the one tall row; the radio fault takes two. */
static void text_han(const modem_screen_state_t *s, modem_screen_text_t *out)
{
    snprintf(out->head_right, sizeof(out->head_right), "%s", link_word(s));
    if (!s->radio_ok) {
        snprintf(out->line[0], sizeof(out->line[0]), "%s", tx(s, TXM_RADIO_FAULT));
        out->tall[0] = true;
        out->inverted[0] = true;
        snprintf(out->line[1], sizeof(out->line[1]), "%s", tx(s, TXM_NO_TX_RX));
        out->tall[1] = true;
        const char *rest = wrap(s->fault, out->line[2]);
        wrap(rest, out->line[3]);
        out->rows = 4;
        return;
    }
    char id[8];
    const char *left, *right;
    game_texts(s, &left, id, sizeof(id), &right);
    snprintf(out->line[0], sizeof(out->line[0]), "%s", left);
    snprintf(out->right[0], sizeof(out->right[0]), "%s", right);
    out->tall[0] = true;
    numbers(s, out, 1);
    out->rows = 5;
}

void modem_screen_text(const modem_screen_state_t *s, modem_screen_text_t *out)
{
    memset(out, 0, sizeof(*out));
    snprintf(out->title, sizeof(out->title), "%s", tx(s, TXM_TITLE));
    if (s->lang == BOX_LANG_ZH_TW) {
        text_han(s, out);
        return;
    }
    out->rows = MODEM_SCREEN_LINES;

    two_col(out->line[0], tx(s, TXM_LINK), link_word(s));
    out->inverted[0] = s->link == MODEM_LINK_DOWN;

    char id[8];
    const char *left, *right;
    game_texts(s, &left, id, sizeof(id), &right);
    two_col(out->line[1], left, right);

    if (!s->radio_ok) {
        two_col(out->line[2], tx(s, TXM_RADIO_FAULT), "");
        out->inverted[2] = true;
        const char *rest = wrap(s->fault, out->line[3]);
        wrap(rest, out->line[4]);
        two_col(out->line[5], tx(s, TXM_NO_TX_RX), "");
        return;
    }
    numbers(s, out, 2);
}

/* ---- Drawing (LVGL) ------------------------------------------------------ */

#if ATALAIA_SCREEN_LVGL

#include "hal_oled.h"
#include "oled_logo.h"
#include "oled_view.h"

#define OLED_W HAL_OLED_WIDTH
#define BAR_H  16
#define LINE_H 8

#define TALL_H 16 /* a Han row: Montserrat 14's line */

static lv_obj_t *title_label, *head_right_label;
static lv_obj_t *lines[MODEM_SCREEN_LINES];
static lv_obj_t *rights[MODEM_SCREEN_LINES]; /* a tall row's right text */
static bool built;

static void clean(lv_obj_t *scr)
{
    lv_obj_clean(scr);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_pad_all(scr, 0, 0);
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    built = false;
}

static lv_obj_t *image(lv_obj_t *parent, lv_image_dsc_t *dsc, const uint8_t *data, int w, int h,
                       lv_color_t colour)
{
    dsc->header.magic = LV_IMAGE_HEADER_MAGIC;
    dsc->header.cf = LV_COLOR_FORMAT_A8;
    dsc->header.w = (uint32_t)w;
    dsc->header.h = (uint32_t)h;
    dsc->header.stride = (uint32_t)w;
    dsc->data = data;
    dsc->data_size = (uint32_t)(w * h);
    lv_obj_t *img = lv_image_create(parent);
    lv_image_set_src(img, dsc);
    lv_obj_set_style_image_recolor(img, colour, 0);
    lv_obj_set_style_image_recolor_opa(img, LV_OPA_COVER, 0);
    return img;
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, const char *s)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_white(), 0);
    lv_label_set_long_mode(l, LV_LABEL_LONG_CLIP);
    lv_label_set_text(l, s);
    return l;
}

static void build(lv_obj_t *scr)
{
    clean(scr);
    lv_obj_t *bar = lv_obj_create(scr);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, OLED_W, BAR_H);
    lv_obj_set_style_bg_color(bar, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);

    static lv_image_dsc_t icon;
    lv_obj_t *img = image(bar, &icon, oled_icon_a8, OLED_ICON_W, OLED_ICON_H, lv_color_black());
    lv_obj_align(img, LV_ALIGN_LEFT_MID, 2, 0);
    title_label = label(bar, &lv_font_atalaia_14, "");
    lv_obj_set_style_text_color(title_label, lv_color_black(), 0);
    lv_obj_align(title_label, LV_ALIGN_LEFT_MID, OLED_ICON_W + 5, 0);
    head_right_label = label(bar, &lv_font_atalaia_14, "");
    lv_obj_set_style_text_color(head_right_label, lv_color_black(), 0);
    lv_obj_align(head_right_label, LV_ALIGN_RIGHT_MID, -3, 0);

    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        lines[i] = label(scr, &lv_font_unscii_8, "");
        lv_obj_set_style_bg_color(lines[i], lv_color_white(), 0);
    }
    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        rights[i] = label(scr, &lv_font_atalaia_14, "");
        lv_obj_set_width(rights[i], LV_SIZE_CONTENT);
    }
    built = true;
}

void modem_screen_draw(lv_obj_t *scr, const modem_screen_text_t *t)
{
    if (!scr) return;
    if (!built) build(scr);
    lv_label_set_text(title_label, t->title);
    lv_label_set_text(head_right_label, t->head_right);
    int32_t y = BAR_H;
    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        bool used = i < t->rows;
        bool tall = used && t->tall[i];
        lv_color_t ink = t->inverted[i] ? lv_color_black() : lv_color_white();
        lv_obj_set_style_text_font(lines[i], tall ? &lv_font_atalaia_14 : &lv_font_unscii_8, 0);
        lv_obj_set_style_pad_left(lines[i], tall ? 2 : 0, 0);
        lv_obj_set_size(lines[i], OLED_W, tall ? TALL_H : LINE_H);
        lv_obj_set_pos(lines[i], 0, y);
        lv_label_set_text(lines[i], used ? t->line[i] : "");
        lv_obj_set_style_bg_opa(lines[i], used && t->inverted[i] ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
        lv_obj_set_style_text_color(lines[i], ink, 0);
        lv_label_set_text(rights[i], tall ? t->right[i] : "");
        lv_obj_set_style_text_color(rights[i], ink, 0);
        lv_obj_align(rights[i], LV_ALIGN_TOP_RIGHT, -2, y);
        y += tall ? TALL_H : LINE_H;
    }
}

void modem_screen_splash(lv_obj_t *scr, const char *version, box_lang_t lang)
{
    if (!scr) return;
    clean(scr);

    static lv_image_dsc_t logo;
    lv_obj_t *img = image(scr, &logo, oled_logo_a8, OLED_LOGO_W, OLED_LOGO_H, lv_color_white());
    lv_obj_align(img, LV_ALIGN_LEFT_MID, OLED_SPLASH_LOGO_X, 0);

    /* The version as on the box's splash (FV-8): Montserrat 14, as unscii 8 holds only 11
     * characters here; a development build's commit on a line of its own, the lines moved up. */
    char line1[40], line2[24];
    oled_version_lines(version, line1, sizeof(line1), line2, sizeof(line2));
    const int32_t x = OLED_SPLASH_TEXT_X;
    const int32_t w = HAL_OLED_WIDTH - x;
    /* The mode's name in the language: unscii 8 (ASCII), or in Chinese Montserrat 14, which is
     * taller, so everything sits closer. */
    const bool han = lang == BOX_LANG_ZH_TW;
    lv_obj_t *name = label(scr, &lv_font_atalaia_20, "ATALAIA");
    lv_obj_align(name, LV_ALIGN_TOP_LEFT, x, han ? 0 : line2[0] ? 1 : 6);
    lv_obj_t *mode =
        label(scr, han ? &lv_font_atalaia_14 : &lv_font_unscii_8, box_text_in(lang, TXM_TITLE));
    lv_obj_align_to(mode, name, LV_ALIGN_OUT_BOTTOM_LEFT, 0, han ? 0 : line2[0] ? 2 : 4);
    lv_obj_t *ver =
        label(scr, &lv_font_atalaia_14, oled_version_fit(line1, &lv_font_atalaia_14, w));
    lv_label_set_long_mode(ver, LV_LABEL_LONG_DOT);
    lv_obj_set_width(ver, w);
    lv_obj_align_to(ver, mode, LV_ALIGN_OUT_BOTTOM_LEFT, 0, han ? 0 : 2);
    if (line2[0]) {
        lv_obj_t *commit = label(scr, &lv_font_unscii_8, line2);
        lv_obj_set_width(commit, w);
        lv_obj_align_to(commit, ver, LV_ALIGN_OUT_BOTTOM_LEFT, 0, 1);
    }
}

#endif /* ATALAIA_SCREEN_LVGL */
