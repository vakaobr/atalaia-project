/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's screen texts (main/box_text.c, decision BN-14): every text in
 * both languages, the OLED's within its 16 characters, only letters the fonts
 * have, and the language codes.
 */
#include <string.h>

#include "box_text.h"
#include "check.h"
#include "screen_template.h"

/* Characters, not bytes (UTF-8). */
static size_t chars(const char *s)
{
    size_t n = 0;
    for (; *s; s++) {
        if (((unsigned char)*s & 0xC0) != 0x80) n++;
    }
    return n;
}

static void test_every_text(void)
{
    for (int id = 0; id < TX_COUNT; id++) {
        for (int lang = 0; lang < BOX_LANG_COUNT; lang++) {
            const char *s = box_text_in((box_lang_t)lang, (box_text_id_t)id);
            CHECK(s != NULL);
            /* Empty only where English has nothing more to say. */
            CHECK(s[0] != '\0' || (id == TX_TO_CAPTURE && lang == BOX_LANG_EN));
            /* The fonts have every letter: folding changes nothing. */
            char folded[128];
            snprintf(folded, sizeof(folded), "%s", s);
            screen_template_fold_text(folded);
            CHECK(strcmp(folded, s) == 0);
            /* The OLED's lines: 16 characters (a few English ones of before take 17). */
            size_t en = chars(box_text_in(BOX_LANG_EN, (box_text_id_t)id));
            if (id >= TXO_ADMIN_PIN) CHECK(chars(s) <= 16 || chars(s) <= en);
        }
    }
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_WAITING_UP), "\xc3\x80 ESPERA") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_EN, TX_NEUTRAL_UP), "NEUTRAL") == 0);
    /* The maintainer's word for a zone nobody holds (BN-14). */
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_NEUTRAL_UP), "LIVRE") == 0);
    CHECK(strcmp(box_text_in(BOX_LANG_COUNT, TX_NEUTRAL_UP), "NEUTRAL") == 0); /* English */
    CHECK(strcmp(box_text_in(BOX_LANG_PT, TX_COUNT), "") == 0);
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
    CHECK(strcmp(box_lang_code(BOX_LANG_PT), "pt") == 0);
    box_lang_set_code("pt");
    CHECK(box_lang() == BOX_LANG_PT && box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "PRONTA") == 0);
    box_lang_set_code("");
    CHECK(box_lang() == BOX_LANG_EN && !box_lang_given());
    CHECK(strcmp(box_text(TX_READY_UP), "READY") == 0);
}

void run_box_text_tests(void)
{
    test_every_text();
    test_language_codes();
}
