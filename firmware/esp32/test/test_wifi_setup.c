/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for the URL-encoded form parser in wifi_setup.c.
 * parse_form_field is platform-independent and testable on Linux.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "box_text.h"
#include "check.h"
#include "wifi_setup.h"

/* ---- parse_form_field tests ---- */

static void test_parse_normal(void)
{
    char out[64];
    CHECK(parse_form_field("name=alpha&region=EU868", "name", out, sizeof(out)));
    CHECK(strcmp(out, "alpha") == 0);

    CHECK(parse_form_field("name=alpha&region=EU868", "region", out, sizeof(out)));
    CHECK(strcmp(out, "EU868") == 0);
}

static void test_parse_url_encoded(void)
{
    char out[64];
    /* %20 -> space */
    CHECK(parse_form_field("name=hello%20world", "name", out, sizeof(out)));
    CHECK(strcmp(out, "hello world") == 0);

    /* + -> space */
    CHECK(parse_form_field("name=hello+world", "name", out, sizeof(out)));
    CHECK(strcmp(out, "hello world") == 0);

    /* %40 -> @ */
    CHECK(parse_form_field("email=user%40host.com", "email", out, sizeof(out)));
    CHECK(strcmp(out, "user@host.com") == 0);

    /* Mixed encoding */
    CHECK(parse_form_field("msg=a+b%21c", "msg", out, sizeof(out)));
    CHECK(strcmp(out, "a b!c") == 0);
}

static void test_parse_oversized_value(void)
{
    char out[8]; /* small buffer */
    /* Value is longer than buffer: should truncate safely. */
    CHECK(parse_form_field("name=abcdefghijklmnop", "name", out, sizeof(out)));
    CHECK(strlen(out) <= 7); /* at most out_sz - 1 */
    CHECK(strncmp(out, "abcdefg", 7) == 0);
}

static void test_parse_missing_field(void)
{
    char out[64] = "untouched";
    CHECK(!parse_form_field("name=alpha&region=EU868", "pin", out, sizeof(out)));
    /* Output should be empty on failure. */
    CHECK(out[0] == '\0');
}

static void test_parse_malformed_input(void)
{
    char out[64];

    /* NULL body */
    CHECK(!parse_form_field(NULL, "name", out, sizeof(out)));

    /* Empty body */
    CHECK(!parse_form_field("", "name", out, sizeof(out)));

    /* No = sign */
    CHECK(!parse_form_field("namevalue", "name", out, sizeof(out)));

    /* Key at end without value */
    CHECK(parse_form_field("name=", "name", out, sizeof(out)));
    CHECK(out[0] == '\0');

    /* Incomplete percent encoding: treat literally */
    CHECK(parse_form_field("name=ab%2", "name", out, sizeof(out)));
    CHECK(strcmp(out, "ab%2") == 0);

    /* Percent with non-hex char */
    CHECK(parse_form_field("name=ab%ZZcd", "name", out, sizeof(out)));
    CHECK(strcmp(out, "ab%ZZcd") == 0);
}

static void test_parse_key_substring(void)
{
    char out[64];
    /* "name" should not match "username". */
    CHECK(!parse_form_field("username=bob", "name", out, sizeof(out)));

    /* But it should match when "name" is a separate field. */
    CHECK(parse_form_field("username=bob&name=alice", "name", out, sizeof(out)));
    CHECK(strcmp(out, "alice") == 0);
}

static void test_parse_first_field(void)
{
    char out[64];
    /* Field at the very start of the body. */
    CHECK(parse_form_field("pin=9876&other=x", "pin", out, sizeof(out)));
    CHECK(strcmp(out, "9876") == 0);
}

/* ---- field validation tests ---- */

static void test_validate_empty_name(void)
{
    char out[64];
    /* Empty name value: parse succeeds but value is empty. */
    CHECK(parse_form_field("name=&region=EU868", "name", out, sizeof(out)));
    CHECK(out[0] == '\0'); /* Caller should reject this. */
}

static void test_validate_bad_region(void)
{
    char out[64];
    CHECK(parse_form_field("region=INVALID", "region", out, sizeof(out)));
    CHECK(strcmp(out, "INVALID") == 0);
    /* Caller validates: INVALID is not the build region (EU868 or AS923-TW) */
}

static void test_validate_non_digit_pin(void)
{
    char out[64];
    CHECK(parse_form_field("pin=12ab", "pin", out, sizeof(out)));
    CHECK(strcmp(out, "12ab") == 0);
    /* Caller validates: contains non-digit chars. */
}

static void test_validate_short_pin(void)
{
    char out[64];
    CHECK(parse_form_field("pin=12", "pin", out, sizeof(out)));
    CHECK(strcmp(out, "12") == 0);
    /* Caller validates: fewer than 4 digits. */
}

/* The setup portal sets a Field Box's first admin PIN; there is no default, and 1234 and the
 * other easy ones are refused with a clear message (decision AD-29). */
static void test_portal_refuses_trivial_pins(void)
{
    CHECK(wifi_setup_pin_problem("4711") == NULL);
    CHECK(wifi_setup_pin_problem("80162") == NULL);
    CHECK(strcmp(wifi_setup_pin_problem("12"), "PIN must be 4-8 digits") == 0);
    CHECK(strcmp(wifi_setup_pin_problem("12ab"), "PIN must be 4-8 digits") == 0);
    CHECK(strcmp(wifi_setup_pin_problem(""), "PIN must be 4-8 digits") == 0);
    static const char *const easy[] = {"1234", "0000", "1111", "4321", "123456", "1212"};
    for (size_t i = 0; i < sizeof(easy) / sizeof(easy[0]); i++) {
        const char *why = wifi_setup_pin_problem(easy[i]);
        CHECK(why != NULL && strstr(why, "too easy to guess") != NULL);
    }
}

/* ---- the page's language ---- */

static void test_pick_lang(void)
{
    box_lang_set_code(""); /* no game has given the box a language */
    CHECK(wifi_setup_pick_lang(NULL, NULL) == BOX_LANG_EN);
    CHECK(wifi_setup_pick_lang("", "") == BOX_LANG_EN);
    /* The browser's, by q value, then order; a language the box lacks is skipped. */
    CHECK(wifi_setup_pick_lang(NULL, "pt-PT,pt;q=0.9,en;q=0.8") == BOX_LANG_PT);
    CHECK(wifi_setup_pick_lang(NULL, "en-US,en;q=0.9,pt;q=0.8") == BOX_LANG_EN);
    CHECK(wifi_setup_pick_lang(NULL, "de-DE,de;q=0.9") == BOX_LANG_DE);
    CHECK(wifi_setup_pick_lang(NULL, "fr-FR,fr;q=0.9,de;q=0.7") == BOX_LANG_DE);
    CHECK(wifi_setup_pick_lang(NULL, "fr-FR,fr;q=0.9") == BOX_LANG_EN);
    CHECK(wifi_setup_pick_lang(NULL, "zh-TW,zh;q=0.9,en;q=0.8") == BOX_LANG_ZH_TW);
    CHECK(wifi_setup_pick_lang(NULL, "zh-Hant-TW") == BOX_LANG_ZH_TW);
    CHECK(wifi_setup_pick_lang(NULL, "zh-CN,zh;q=0.9") == BOX_LANG_EN);   /* Simplified: not here */
    CHECK(wifi_setup_pick_lang(NULL, "pt;q=0, de;q=0.5") == BOX_LANG_DE); /* q=0: not wanted */
    CHECK(wifi_setup_pick_lang(NULL, "*") == BOX_LANG_EN);
    CHECK(wifi_setup_pick_lang(NULL, ",,;q=,pt;q=x") == BOX_LANG_PT);
    CHECK(wifi_setup_pick_lang(NULL, "averyveryverylongtag-pt-PT-xx,pt") == BOX_LANG_PT);
    /* The box's own language, when a game gave one, beats the browser's. */
    box_lang_set_code("de");
    CHECK(wifi_setup_pick_lang(NULL, "pt-PT,pt;q=0.9") == BOX_LANG_DE);
    /* "?lang=" beats both. */
    CHECK(wifi_setup_pick_lang("pt", "") == BOX_LANG_PT);
    CHECK(wifi_setup_pick_lang("zh-tw", NULL) == BOX_LANG_ZH_TW);
    CHECK(wifi_setup_pick_lang("en", "de") == BOX_LANG_EN);
    box_lang_set_code("");
}

/* Every answer in every language, and the PIN's two reasons. */
static void test_messages(void)
{
    for (int m = 0; m < WS_MSG_COUNT; m++) {
        for (int l = 0; l < BOX_LANG_COUNT; l++) {
            const char *t = wifi_setup_msg((box_lang_t)l, (wifi_setup_msg_t)m);
            CHECK(t != NULL && t[0] != '\0');
            /* Only the region message has a value to fill in. */
            CHECK((strchr(t, '%') != NULL) == (m == WS_MSG_REGION));
        }
    }
    CHECK(strcmp(wifi_setup_msg(BOX_LANG_PT, WS_MSG_SAVED), "Guardado. A reiniciar...") == 0);
    CHECK(strstr(wifi_setup_msg(BOX_LANG_PT, WS_MSG_PIN_WEAK), "Escolhe outro") != NULL);
    CHECK(strcmp(wifi_setup_pin_problem_in(BOX_LANG_DE, "12"), "Die PIN muss 4-8 Ziffern haben") ==
          0);
    CHECK(strstr(wifi_setup_pin_problem_in(BOX_LANG_ZH_TW, "1234"), "1234") != NULL);
    CHECK(wifi_setup_pin_problem_in(BOX_LANG_PT, "4711") == NULL);
    CHECK(wifi_setup_msg(BOX_LANG_EN, WS_MSG_COUNT)[0] == '\0');
}

/* The page: one marker for the language, a text for each key in each language it has. */
static void test_page_texts(void)
{
    FILE *f = fopen(WIFI_SETUP_HTML, "rb");
    CHECK(f != NULL);
    if (f == NULL) return;
    static char html[16384];
    size_t n = fread(html, 1, sizeof(html) - 1, f);
    fclose(f);
    html[n] = '\0';
    CHECK(n > 1000 && n < sizeof(html) - 1);
    CHECK(strstr(html, "@LANG@") != NULL && strstr(strstr(html, "@LANG@") + 1, "@LANG@") == NULL);
    /* Every data-i key of the page is in each language's table of the script, and no more. */
    int keys = 0;
    for (const char *p = html; (p = strstr(p, "data-i=\"")) != NULL; p++) {
        char key[16];
        const char *k = p + 8;
        size_t kl = strcspn(k, "\"");
        CHECK(kl > 0 && kl < sizeof(key));
        snprintf(key, sizeof(key), "%.*s", (int)kl, k);
        char want[24];
        snprintf(want, sizeof(want), "%s:\"", key);
        const char *script = strstr(html, "<script>");
        CHECK(script != NULL);
        int found = 0;
        for (const char *q = script; (q = strstr(q, want)) != NULL; q++) {
            if (q[-1] == '{' || q[-1] == ',') found++;
        }
        CHECK(found == 3); /* pt, de and zh-tw; English is the page */
        keys++;
    }
    CHECK(keys >= 14);
    /* Each language's table is there once, with the title. */
    CHECK(strstr(html, "pt:{t:\"") != NULL && strstr(html, "de:{t:\"") != NULL &&
          strstr(html, "\"zh-tw\":{t:\"") != NULL);
}

/* ---- the captive portal's DNS ---- */

static const uint8_t portal_ip[4] = {192, 168, 4, 1};

/* A query for name (dotted) of type, with an EDNS OPT record as phones add. */
static size_t make_query(uint8_t *q, const char *name, unsigned type, bool edns)
{
    size_t i = 0;
    q[i++] = 0x12, q[i++] = 0x34; /* id */
    q[i++] = 0x01, q[i++] = 0x00; /* standard query, RD */
    q[i++] = 0, q[i++] = 1;       /* one question */
    q[i++] = 0, q[i++] = 0, q[i++] = 0, q[i++] = 0;
    q[i++] = 0, q[i++] = edns ? 1 : 0;
    for (const char *p = name; *p;) {
        size_t l = strcspn(p, ".");
        q[i++] = (uint8_t)l;
        memcpy(q + i, p, l);
        i += l;
        p += l + (p[l] == '.');
    }
    q[i++] = 0;
    q[i++] = (uint8_t)(type >> 8), q[i++] = (uint8_t)type;
    q[i++] = 0, q[i++] = 1; /* IN */
    if (edns) {
        const uint8_t opt[] = {0, 0, 41, 16, 0, 0, 0, 0, 0, 0, 0};
        memcpy(q + i, opt, sizeof(opt));
        i += sizeof(opt);
    }
    return i;
}

static void test_dns_answers_every_name(void)
{
    uint8_t q[128], out[256];
    static const char *const names[] = {"example.com", "connectivitycheck.gstatic.com",
                                        "captive.apple.com", "www.msftconnecttest.com", "a"};
    for (size_t k = 0; k < sizeof(names) / sizeof(names[0]); k++) {
        size_t n = make_query(q, names[k], 1, true);
        size_t m = wifi_setup_dns_reply(q, n, out, sizeof(out), portal_ip);
        size_t qend = n - 11; /* the question ends where the OPT record starts */
        CHECK(m == qend + 16);
        CHECK(out[0] == 0x12 && out[1] == 0x34);             /* the same id */
        CHECK((out[2] & 0x80) != 0 && (out[2] & 0x01) != 0); /* a response, RD copied */
        CHECK((out[3] & 0x0F) == 0);                         /* NOERROR */
        CHECK(out[5] == 1 && out[7] == 1 && out[9] == 0 && out[11] == 0);
        CHECK(memcmp(out + 12, q + 12, qend - 12) == 0); /* the question, as asked */
        CHECK(m >= 4 && memcmp(out + m - 4, portal_ip, 4) == 0);
        CHECK(out[qend] == 0xC0 && out[qend + 1] == 12);   /* the name, by pointer */
        CHECK(out[qend + 3] == 1 && out[qend + 5] == 1);   /* A, IN */
        CHECK(out[qend + 10] == 0 && out[qend + 11] == 4); /* four bytes of address */
    }
    /* ANY is answered as A. */
    size_t n = make_query(q, "x.y", 255, false);
    CHECK(wifi_setup_dns_reply(q, n, out, sizeof(out), portal_ip) == n + 16);
    /* AAAA, HTTPS, TXT ...: no answer, but a clean one, so a phone goes on to A. */
    unsigned other[] = {28, 65, 16, 15};
    for (size_t k = 0; k < sizeof(other) / sizeof(other[0]); k++) {
        n = make_query(q, "example.com", other[k], false);
        size_t m = wifi_setup_dns_reply(q, n, out, sizeof(out), portal_ip);
        CHECK(m == n);
        CHECK((out[2] & 0x80) != 0 && (out[3] & 0x0F) == 0 && out[7] == 0);
    }
}

static void test_dns_ignores_what_is_not_a_query(void)
{
    uint8_t q[128], out[256];
    size_t n = make_query(q, "example.com", 1, false);
    CHECK(wifi_setup_dns_reply(q, n, out, sizeof(out), portal_ip) > 0);
    /* Too short, too long, a cut name, a cut question. */
    CHECK(wifi_setup_dns_reply(q, 0, out, sizeof(out), portal_ip) == 0);
    CHECK(wifi_setup_dns_reply(q, 12, out, sizeof(out), portal_ip) == 0);
    CHECK(wifi_setup_dns_reply(q, 20, out, sizeof(out), portal_ip) == 0);
    CHECK(wifi_setup_dns_reply(q, n - 1, out, sizeof(out), portal_ip) == 0);
    CHECK(wifi_setup_dns_reply(q, 600, out, sizeof(out), portal_ip) == 0);
    /* A response (QR), another opcode, no question or two. */
    uint8_t w[128];
    memcpy(w, q, n);
    w[2] |= 0x80;
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    memcpy(w, q, n);
    w[2] |= 0x10; /* opcode 2: status */
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    memcpy(w, q, n);
    w[5] = 0;
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    memcpy(w, q, n);
    w[5] = 2;
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    /* A compressed name in the question, a label running past the packet. */
    memcpy(w, q, n);
    w[12] = 0xC0;
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    memcpy(w, q, n);
    w[12] = 60;
    CHECK(wifi_setup_dns_reply(w, n, out, sizeof(out), portal_ip) == 0);
    /* Not enough room for the answer. */
    CHECK(wifi_setup_dns_reply(q, n, out, n + 15, portal_ip) == 0);
    CHECK(wifi_setup_dns_reply(q, n, out, n + 16, portal_ip) == n + 16);
    CHECK(wifi_setup_dns_reply(q, n, NULL, sizeof(out), portal_ip) == 0);
    /* Whatever the bytes, it never writes past cap or reads past len. */
    for (unsigned seed = 1; seed < 4000; seed++) {
        uint8_t junk[64];
        unsigned x = seed * 2654435761u;
        size_t len = 12 + seed % 52;
        for (size_t i = 0; i < len; i++) {
            x = x * 1103515245u + 12345u;
            junk[i] = (uint8_t)(x >> 16);
        }
        junk[2] &= 0x07, junk[4] = 0, junk[5] = 1;
        uint8_t o[96];
        memset(o, 0xAA, sizeof(o));
        size_t m = wifi_setup_dns_reply(junk, len, o, 80, portal_ip);
        CHECK(m <= 80);
        for (size_t i = 80; i < sizeof(o); i++) CHECK(o[i] == 0xAA);
    }
}

/* ---- entry point ---- */

void run_wifi_setup_tests(void)
{
    test_pick_lang();
    test_messages();
    test_page_texts();
    test_dns_answers_every_name();
    test_dns_ignores_what_is_not_a_query();
    test_parse_normal();
    test_parse_url_encoded();
    test_parse_oversized_value();
    test_parse_missing_field();
    test_parse_malformed_input();
    test_parse_key_substring();
    test_parse_first_field();
    test_validate_empty_name();
    test_validate_bad_region();
    test_validate_non_digit_pin();
    test_validate_short_pin();
    test_portal_refuses_trivial_pins();
}
