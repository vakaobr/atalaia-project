/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's screen texts (main/box_text.c, decisions BN-14, P5H-4, P5K-2):
 * every text in every language, the OLED's within its 16 columns, only letters
 * the fonts have, and the language codes. The screens with the texts are
 * checked by the "_pt", "_de" and "_zh-tw" reference images (test_screens.c,
 * test_oled_screens.c).
 */
#include <string.h>

#include "box_text.h"
#include "check.h"
#include "font_check.h"
#include "screen_template.h"

extern const lv_font_t lv_font_atalaia_14, lv_font_atalaia_20, lv_font_atalaia_28,
    lv_font_atalaia_48;

/* Han letters, CJK punctuation, full-width forms (as tools/gen_box_fonts.py's is_cjk). */
static bool wide(uint32_t cp)
{
    return (cp >= 0x2E80 && cp <= 0x9FFF) || (cp >= 0xF900 && cp <= 0xFAFF) ||
           (cp >= 0xFF00 && cp <= 0xFFEF);
}

/* Columns on a fixed grid: a Han letter or full-width sign takes two. */
static size_t columns(const char *s)
{
    size_t n = 0, i = 0;
    for (uint32_t cp; (cp = font_check_next(s, &i)) != 0;) n += wide(cp) ? 2 : 1;
    return n;
}

/* The texts the TFT draws at 48 px (tools/gen_box_fonts.py's AT_48). */
static bool at_48(int id)
{
    return id == TX_DEFUSED_UP || id == TX_EXPLODED_UP || id == TX_PAUSED_UP ||
           id == TX_NEUTRAL_UP || id == TX_NEXT_GAME || id == TX_GAME_N || id == TX_NO_LIMIT;
}

static void test_every_text(void)
{
    for (int id = 0; id < TX_COUNT; id++) {
        for (int lang = 0; lang < BOX_LANG_COUNT; lang++) {
            const char *s = box_text_in((box_lang_t)lang, (box_text_id_t)id);
            CHECK(s != NULL);
            /* Empty only where English has nothing more to say. */
            CHECK(s[0] != '\0' || (id == TX_TO_CAPTURE && lang == BOX_LANG_EN));
            /* The fonts have every letter, at every size the box draws texts in (P5K-3). */
            uint32_t missing = 0;
            CHECK(font_check_text(&lv_font_atalaia_14, s, &missing));
            CHECK(font_check_text(&lv_font_atalaia_20, s, &missing));
            CHECK(font_check_text(&lv_font_atalaia_28, s, &missing));
            if (at_48(id)) CHECK(font_check_text(&lv_font_atalaia_48, s, &missing));
            /* Folding (the templates' filter) changes nothing either, Chinese included: the
             * fonts' tables have every letter at 14, 20 and 28 px (box_fonts_cjk.h, P5H-12). */
            for (int px = 14; px <= 28; px += px == 14 ? 6 : 8) {
                char folded[128];
                snprintf(folded, sizeof(folded), "%s", s);
                screen_template_fold_text(folded, px);
                CHECK(strcmp(folded, s) == 0);
            }
            /* The OLED's lines: 16 columns, a Han letter two (a few English ones of before
             * take 17). */
            size_t en = columns(box_text_in(BOX_LANG_EN, (box_text_id_t)id));
            if (id >= TXO_ADMIN_PIN) CHECK(columns(s) <= 16 || columns(s) <= en);
        }
    }
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_WAITING_UP), "\xc3\x80 ESPERA") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_EN, TX_NEUTRAL_UP), "NEUTRAL") == 0);
    /* The maintainer's word for a zone nobody holds (BN-14). */
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_NEUTRAL_UP), "LIVRE") == 0);
    /* German (P5H-4): a zone nobody holds is FREI; the game's end is not "Spielende" (players). */
    CHECK(strcmp(box_text_in(BOX_LANG_DE, TX_NEUTRAL_UP), "FREI") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_DE, TX_DEFUSED_UP), "ENTSCH\xc3\x84RFT") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_DE, TX_GAME_OVER_UP), "SPIEL VORBEI") == 0);
    /* Traditional Chinese (P5K-2): 中立 for a zone nobody holds, 據點 for the zone. */
    CHECK(strcmp(box_text_in(BOX_LANG_ZH_TW, TX_NEUTRAL_UP), "中立") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_ZH_TW, TX_ZONE_UP), "據點") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_COUNT, TX_NEUTRAL_UP), "NEUTRAL") == 0); /* English */
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_COUNT), "") == 0);
}

/* Taiwan's punctuation (zh-TW): full-width after a Han letter, never a half-width , : ; ! ?
 * (the keypad hints' "#" and "*" and the clock's ":" follow digits or spaces, not Han). */
static void test_chinese_punctuation(void)
{
    for (int id = 0; id < TX_COUNT; id++) {
        const char *s = box_text_in(BOX_LANG_ZH_TW, (box_text_id_t)id);
        size_t i = 0;
        bool after_han = false;
        for (uint32_t cp; (cp = font_check_next(s, &i)) != 0;) {
            if (after_han) CHECK(cp != ',' && cp != ':' && cp != ';' && cp != '!' && cp != '?');
            after_han = cp >= 0x3400 && cp <= 0x9FFF;
        }
    }
}

static void test_language_codes(void)
{
    CHECK(box_lang_from_code("pt") == BOX_LANG_PT);
    CHECK(box_lang_from_code("pt-br") == BOX_LANG_PT);
    CHECK(box_lang_from_code("en") == BOX_LANG_EN);
    CHECK(box_lang_from_code("fr") == BOX_LANG_EN);
    CHECK(box_lang_from_code("ptx") == BOX_LANG_EN);
    CHECK(box_lang_from_code("") == BOX_LANG_EN);
    CHECK(box_lang_from_code(NULL) == BOX_LANG_EN);
    CHECK(box_lang_from_code("de") == BOX_LANG_DE);
    CHECK(box_lang_from_code("de-at") == BOX_LANG_DE);
    CHECK(box_lang_from_code("dex") == BOX_LANG_EN);
    CHECK(box_lang_from_code("d") == BOX_LANG_EN);
    /* Traditional Chinese: zh-tw or zh-hant, with or without more subtags; Simplified and plain
     * "zh" are English (the box has no Simplified Chinese). */
    CHECK(box_lang_from_code("zh-tw") == BOX_LANG_ZH_TW);
    CHECK(box_lang_from_code("zh-hant") == BOX_LANG_ZH_TW);
    CHECK(box_lang_from_code("zh-hant-tw") == BOX_LANG_ZH_TW);
    CHECK(box_lang_from_code("zh-tw-x") == BOX_LANG_ZH_TW);
    CHECK(box_lang_from_code("zh") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-cn") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-hans") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-hans-tw") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-twx") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zh-hantx") == BOX_LANG_EN);
    CHECK(box_lang_from_code("zhx-tw") == BOX_LANG_EN);
    CHECK(strcmp(box_lang_code(BOX_LANG_PT), "pt") == 0);
    CHECK(strcmp(box_lang_code(BOX_LANG_DE), "de") == 0);
    CHECK(strcmp(box_lang_code(BOX_LANG_ZH_TW), "zh-tw") == 0);
    CHECK(strcmp(box_lang_code(BOX_LANG_EN), "en") == 0);
    CHECK(strcmp(box_lang_code(BOX_LANG_COUNT), "en") == 0);
    box_lang_set_code("de");
    CHECK(box_lang() == BOX_LANG_DE && box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "BEREIT") == 0);
    box_lang_set_code("zh-tw");
    CHECK(box_lang() == BOX_LANG_ZH_TW && box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "就緒") == 0);
    box_lang_set_code("pt");
    CHECK(box_lang() == BOX_LANG_PT && box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "PRONTA") == 0);
    box_lang_set_code("");
    CHECK(box_lang() == BOX_LANG_EN && !box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "READY") == 0);
}

/* The built-in modes' names for the OLED's header, the templates' for its middle line and the
 * keypad's titles: in the box's language, never for English (the raw name stays) or an unknown
 * one. */
static void test_names(void)
{
    box_lang_set(BOX_LANG_EN);
    CHECK(box_text_mode_name("BOMB") == NULL);
    CHECK(box_text_screen_name("defused") == NULL);
    CHECK(strcmp(box_text_title("ARM"), "ARM") == 0);
    CHECK(strcmp(box_text_title("defuse"), "DEFUSE") == 0);
    CHECK(strcmp(box_text_title("Hello"), "Hello") == 0);
    CHECK(strcmp(box_text_title(NULL), "") == 0);

    box_lang_set(BOX_LANG_PT);
    CHECK(strcmp(box_text_mode_name("KILL CONFIRMED"), "BAIXA CONF.") == 0);
    CHECK(strcmp(box_text_screen_name("exploded"), "EXPLODIU") == 0);
    CHECK(strcmp(box_text_screen_name("medic_idle"), "PRONTA") == 0);
    CHECK(box_text_mode_name("ACME HILL") == NULL);
    CHECK(box_text_screen_name("my_screen") == NULL);
    CHECK(box_text_screen_name(NULL) == NULL);
    CHECK(strcmp(box_text_title("CODE"), "C\xc3\x93"
                                         "DIGO") == 0);

    box_lang_set(BOX_LANG_DE);
    CHECK(strcmp(box_text_screen_name("defused"), "ENTSCH\xc3\x84RFT") == 0);
    CHECK(strcmp(box_text_mode_name("TARGET WINDOWS"), "ZIELFENSTER") == 0);

    box_lang_set(BOX_LANG_ZH_TW);
    CHECK(strcmp(box_text_screen_name("defused"), "已拆除") == 0);
    CHECK(strcmp(box_text_mode_name("CODES"), "密碼") == 0);
    CHECK(strcmp(box_text_title("DEFUSE"), "拆除") == 0);
    /* The pairing code of the status screen is a 代碼 (P5K-16), the keypad's a 密碼. */
    CHECK(strcmp(box_text(TX_ROW_CODE), "代碼") == 0);
    CHECK(strcmp(box_text(TX_CODE_UP), "密碼") == 0);
    box_lang_set(BOX_LANG_EN);
}

/* An empty "lang" parameter takes the box's language; anything else is left alone. */
static void test_fill_lang(void)
{
    char out[96];
    box_lang_set_code("pt");
    CHECK(strcmp(box_text_fill_lang("{\"lang\":\"\"}", out, sizeof(out)), "{\"lang\":\"pt\"}") ==
          0);
    CHECK(strcmp(box_text_fill_lang("{\"a\":1,\"lang\": \"\" ,\"b\":2}", out, sizeof(out)),
                 "{\"a\":1,\"lang\": \"pt\" ,\"b\":2}") == 0);
    box_lang_set_code("zh-tw");
    CHECK(strcmp(box_text_fill_lang("{\"lang\":\"\",\"x\":true}", out, sizeof(out)),
                 "{\"lang\":\"zh-tw\",\"x\":true}") == 0);
    box_lang_set_code(""); /* no game language: English */
    CHECK(strcmp(box_text_fill_lang("{\"lang\":\"\"}", out, sizeof(out)), "{\"lang\":\"en\"}") ==
          0);
    box_lang_set_code("de");
    /* Left as it is: a value, no key, another key, a quoted key inside a string, no JSON. */
    const char *same[] = {"{\"lang\":\"pt\"}",
                          "{}",
                          "",
                          "{\"language\":\"\"}",
                          "{\"codes\":\"\\\"lang\\\":\\\"\\\"\"}",
                          "{\"lang\":5}"};
    for (size_t i = 0; i < sizeof(same) / sizeof(same[0]); i++) {
        CHECK(box_text_fill_lang(same[i], out, sizeof(out)) == same[i]);
    }
    /* Too small a buffer: the parameters unchanged, never cut. */
    const char *tiny = "{\"lang\":\"\"}";
    CHECK(box_text_fill_lang(tiny, out, 12) == tiny);
    CHECK(box_text_fill_lang(NULL, out, sizeof(out)) == NULL);
    box_lang_set_code("");
}

void run_box_text_tests(void)
{
    test_fill_lang();
    test_every_text();
    test_names();
    test_chinese_punctuation();
    test_language_codes();
}
