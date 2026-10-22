/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Every letter a screen shows must be in the font its label uses, not only in
 * a fallback: LVGL draws a letter no font has as an empty box (tofu,
 * LV_USE_FONT_PLACEHOLDER), and the 48 px font borrows the Chinese letters it
 * lacks from the 28 px one, smaller (tools/gen_box_fonts.py, decision P5K-3).
 * The box's fonts carry only the letters of its own texts, so a new text with
 * a letter they lack fails here, on the screen that shows it, and in
 * tools/gen_box_fonts.py --check. Used by test_screens.c, test_oled_screens.c
 * and test_box_text.c.
 */
#ifndef ATALAIA_FW_TEST_FONT_CHECK_H
#define ATALAIA_FW_TEST_FONT_CHECK_H

#include <stdbool.h>
#include <stdio.h>

#include "lvgl.h"

/* The next code point of UTF-8 s at *i (0 at the end). */
static inline uint32_t font_check_next(const char *s, size_t *i)
{
    const unsigned char *p = (const unsigned char *)s + *i;
    if (!p[0]) return 0;
    int len = p[0] >= 0xF0 ? 4 : p[0] >= 0xE0 ? 3 : p[0] >= 0xC0 ? 2 : 1;
    uint32_t cp = len == 1 ? p[0] : (uint32_t)(p[0] & (0x3F >> (len - 1)));
    int k = 1;
    for (; k < len && p[k]; k++) cp = (cp << 6) | (p[k] & 0x3Fu);
    *i += (size_t)k;
    return cp;
}

/* True when font itself (no fallback) has every letter of text; else the first one it lacks. */
static inline bool font_check_text(const lv_font_t *font, const char *text, uint32_t *missing)
{
    size_t i = 0;
    for (;;) {
        uint32_t letter = font_check_next(text, &i);
        if (letter == 0) return true;
        if (letter == '\n' || letter == '\r') continue;
        lv_font_glyph_dsc_t dsc;
        if (!font->get_glyph_dsc(font, &dsc, letter, 0)) {
            *missing = letter;
            return false;
        }
    }
}

static inline const char *font_check_name(const lv_font_t *font)
{
    extern const lv_font_t lv_font_atalaia_14, lv_font_atalaia_20, lv_font_atalaia_28,
        lv_font_atalaia_48;
    if (font == &lv_font_atalaia_14) return "14 px";
    if (font == &lv_font_atalaia_20) return "20 px";
    if (font == &lv_font_atalaia_28) return "28 px";
    if (font == &lv_font_atalaia_48) return "48 px";
    return "another font";
}

/* Checks every visible label under obj; writes the first problem to msg. Returns the number of
 * labels with a letter their font lacks. */
static inline int font_check_labels(lv_obj_t *obj, char *msg, size_t msg_sz)
{
    int bad = 0;
    uint32_t n = lv_obj_get_child_count(obj);
    for (uint32_t k = 0; k < n; k++) {
        lv_obj_t *child = lv_obj_get_child(obj, (int32_t)k);
        if (lv_obj_has_flag(child, LV_OBJ_FLAG_HIDDEN)) continue;
        if (lv_obj_check_type(child, &lv_label_class)) {
            const lv_font_t *font = lv_obj_get_style_text_font(child, LV_PART_MAIN);
            const char *text = lv_label_get_text(child);
            uint32_t missing = 0;
            if (text && !font_check_text(font, text, &missing)) {
                if (bad == 0) {
                    snprintf(msg, msg_sz, "\"%s\" needs U+%04X, which its %s font lacks", text,
                             (unsigned)missing, font_check_name(font));
                }
                bad++;
            }
        }
        bad += font_check_labels(child, bad ? NULL : msg, bad ? 0 : msg_sz);
    }
    return bad;
}

#endif /* ATALAIA_FW_TEST_FONT_CHECK_H */
