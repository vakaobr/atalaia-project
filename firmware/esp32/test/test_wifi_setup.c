/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for the URL-encoded form parser in wifi_setup.c.
 * parse_form_field is platform-independent and testable on Linux.
 */
#include <stdio.h>
#include <string.h>

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

/* ---- entry point ---- */

void run_wifi_setup_tests(void)
{
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
