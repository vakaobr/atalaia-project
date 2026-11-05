/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The "@wifi" line's arguments (wifi_args.h, decisions WIFI-1 to WIFI-9): the unquoted form as
 * before, double quotes with \" and \\ for names and passwords with spaces, the errors, the
 * SSID's 32 bytes and the password's 8-63 characters or 64 hex digits.
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "serial_console.h"
#include "wifi_args.h"

static char ssid[WIFI_SSID_MAX + 1], pass[WIFI_PASS_MAX + 1];

static bool ok(const char *args, const char *want_ssid, const char *want_pass)
{
    memset(ssid, 'x', sizeof(ssid));
    memset(pass, 'x', sizeof(pass));
    return wifi_args_parse(args, ssid, pass) == WIFI_ARGS_OK && strcmp(ssid, want_ssid) == 0 &&
           strcmp(pass, want_pass) == 0;
}

static bool refused(const char *args, wifi_args_result_t want)
{
    memset(ssid, 'x', sizeof(ssid));
    memset(pass, 'x', sizeof(pass));
    return wifi_args_parse(args, ssid, pass) == want && ssid[0] == '\0' && pass[0] == '\0';
}

static void test_unquoted_as_before(void)
{
    CHECK(ok("CAMPO segredo123", "CAMPO", "segredo123"));
    CHECK(ok("CAMPO", "CAMPO", ""));  /* an open network */
    CHECK(ok("CAMPO ", "CAMPO", "")); /* a trailing space: still open, as before */
    /* The password is the rest of the line as typed, spaces and quotes inside included. */
    CHECK(ok("CAMPO pass word", "CAMPO", "pass word"));
    CHECK(ok("CAMPO  leading", "CAMPO", " leading"));
    CHECK(ok("CAMPO trailing ", "CAMPO", "trailing "));
    CHECK(ok("CAMPO a\"b\\c d12", "CAMPO", "a\"b\\c d12"));
    /* A quote or a backslash inside an unquoted SSID is part of it. */
    CHECK(ok("my\"net\\x secret12", "my\"net\\x", "secret12"));
    CHECK(refused("", WIFI_ARGS_NO_SSID));
    CHECK(refused(" CAMPO segredo123", WIFI_ARGS_NO_SSID));
}

static void test_quoted(void)
{
    CHECK(ok("\"My Field\" \"pass word\"", "My Field", "pass word"));
    CHECK(ok("\"My Field\" pass word", "My Field", "pass word")); /* the rest, as before */
    CHECK(ok("\"My Field\"", "My Field", ""));
    CHECK(ok("\"My Field\" \"\"", "My Field", "")); /* an open network, said */
    CHECK(ok("CAMPO \"pass word\"", "CAMPO", "pass word"));
    CHECK(ok("\"CAMPO\" \"segredo123\"   ", "CAMPO", "segredo123")); /* trailing spaces */
    CHECK(ok("\" lead and trail \" \" 12345678 \"", " lead and trail ", " 12345678 "));
    /* Escapes: \" and \\ only. */
    CHECK(ok("\"say \\\"hi\\\"\" \"back\\\\slash\"", "say \"hi\"", "back\\slash"));
    CHECK(ok("\"\\\\\" \"\\\"\\\"\\\"\\\"\\\"\\\"\\\"\\\"\"", "\\", "\"\"\"\"\"\"\"\""));
    /* UTF-8 passes through: the limit is bytes. */
    CHECK(ok("\"Campo Último Elemento\" \"palavra passe\"", "Campo Último Elemento",
             "palavra passe"));
}

static void test_errors(void)
{
    CHECK(refused("\"My Field", WIFI_ARGS_UNTERMINATED));
    CHECK(refused("\"My Field\" \"pass word", WIFI_ARGS_UNTERMINATED));
    CHECK(refused("\"My Field\\\"", WIFI_ARGS_UNTERMINATED)); /* the quote is escaped */
    CHECK(refused("\"My Field\\", WIFI_ARGS_UNTERMINATED));
    CHECK(refused("\"My\\n Field\" segredo123", WIFI_ARGS_BAD_ESCAPE));
    CHECK(refused("CAMPO \"a\\tb12345678\"", WIFI_ARGS_BAD_ESCAPE));
    CHECK(refused("\"My Field\"x segredo123", WIFI_ARGS_AFTER_QUOTE));
    CHECK(refused("\"My Field\" \"pass word\" extra", WIFI_ARGS_AFTER_QUOTE));
    CHECK(refused("\"My Field\" \"pass word\"x", WIFI_ARGS_AFTER_QUOTE));
    CHECK(refused("\"\" segredo123", WIFI_ARGS_SSID_LENGTH));
    for (int r = WIFI_ARGS_OK; r <= WIFI_ARGS_PASSWORD_LENGTH; r++) {
        CHECK(wifi_args_error((wifi_args_result_t)r)[0] != '\0');
    }
    CHECK(strcmp(wifi_args_error(WIFI_ARGS_OK), "stored") == 0);
    /* An error line never carries what was typed (the password stays off the log). */
    CHECK(strstr(wifi_args_error(WIFI_ARGS_PASSWORD_LENGTH), "8-63") != NULL);
}

static void test_limits(void)
{
    char line[256], want[80];
    /* SSID: 32 bytes, quoted or not; 33 refused. */
    memset(want, 'S', 32);
    want[32] = '\0';
    snprintf(line, sizeof(line), "%s segredo123", want);
    CHECK(ok(line, want, "segredo123"));
    snprintf(line, sizeof(line), "\"%s\" segredo123", want);
    CHECK(ok(line, want, "segredo123"));
    snprintf(line, sizeof(line), "S%s segredo123", want);
    CHECK(refused(line, WIFI_ARGS_SSID_LENGTH));
    snprintf(line, sizeof(line), "\"S%s\" segredo123", want);
    CHECK(refused(line, WIFI_ARGS_SSID_LENGTH));
    /* 31 spaces and an escaped quote: 32 bytes once unescaped. */
    snprintf(line, sizeof(line), "\"%31s\\\"\" segredo123", "");
    CHECK(wifi_args_parse(line, ssid, pass) == WIFI_ARGS_OK && strlen(ssid) == 32 &&
          ssid[31] == '"');
    /* A long name still reports an unclosed quote, not its length. */
    snprintf(line, sizeof(line), "\"S%s segredo123", want);
    CHECK(refused(line, WIFI_ARGS_UNTERMINATED));

    /* Password: 1-7 refused, 8 and 63 taken, 64 only as hex digits, 65 refused. */
    CHECK(refused("CAMPO 1234567", WIFI_ARGS_PASSWORD_LENGTH));
    CHECK(refused("CAMPO \"1234 67\"", WIFI_ARGS_PASSWORD_LENGTH));
    CHECK(ok("CAMPO 12345678", "CAMPO", "12345678"));
    memset(want, 'p', 63);
    want[63] = '\0';
    snprintf(line, sizeof(line), "CAMPO %s", want);
    CHECK(ok(line, "CAMPO", want));
    snprintf(line, sizeof(line), "CAMPO \"%s\"", want);
    CHECK(ok(line, "CAMPO", want));
    snprintf(line, sizeof(line), "CAMPO p%s", want); /* 64, not hex */
    CHECK(refused(line, WIFI_ARGS_PASSWORD_LENGTH));
    snprintf(line, sizeof(line), "CAMPO \"p%s\"", want);
    CHECK(refused(line, WIFI_ARGS_PASSWORD_LENGTH));
    const char *hex = "0123456789abcdefABCDEF0123456789abcdef0123456789abcdef0123456789";
    CHECK(strlen(hex) == 64);
    snprintf(line, sizeof(line), "\"My Field\" %s", hex);
    CHECK(ok(line, "My Field", hex));
    snprintf(line, sizeof(line), "\"My Field\" \"%s\"", hex);
    CHECK(ok(line, "My Field", hex));
    snprintf(line, sizeof(line), "CAMPO %s0", hex); /* 65 */
    CHECK(refused(line, WIFI_ARGS_PASSWORD_LENGTH));
    snprintf(line, sizeof(line), "CAMPO \"%s0\"", hex);
    CHECK(refused(line, WIFI_ARGS_PASSWORD_LENGTH));

    CHECK(wifi_pass_valid("") && wifi_pass_valid("12345678") && wifi_pass_valid(hex));
    CHECK(!wifi_pass_valid("1234567"));
}

/* The line as the console hands it over: quotes and spaces reach the parser untouched. */
static void test_through_console(void)
{
    serial_console_t c;
    serial_console_init(&c);
    const char *typed = "@wifi \"My Field 2\" \"pass word 9\"\r\n";
    const char *line = NULL;
    for (const char *p = typed; *p; p++) {
        char key;
        const char *cmd = NULL;
        if (serial_console_feed(&c, *p, &key, &cmd) == SERIAL_COMMAND) line = cmd;
    }
    CHECK(line != NULL && strncmp(line, "wifi ", 5) == 0);
    if (line != NULL) CHECK(ok(line + 5, "My Field 2", "pass word 9"));
}

void run_wifi_args_tests(void)
{
    test_unquoted_as_before();
    test_quoted();
    test_errors();
    test_limits();
    test_through_console();
}
