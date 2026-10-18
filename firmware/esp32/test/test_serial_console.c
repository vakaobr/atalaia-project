/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The serial console parser: keypad keys, '@' command lines (the join text
 * is full of digits that must not become keys), over-long lines.
 */
#include <string.h>

#include "check.h"
#include "serial_console.h"

static int feed(serial_console_t *c, const char *s, char *keys, char *cmd, size_t cmd_cap)
{
    int commands = 0;
    size_t nk = 0;
    for (const char *p = s; *p; p++) {
        char key;
        const char *line = NULL;
        serial_input_t in = serial_console_feed(c, *p, &key, &line);
        if (in == SERIAL_KEY) keys[nk++] = key;
        if (in == SERIAL_COMMAND) {
            strncpy(cmd, line, cmd_cap - 1);
            cmd[cmd_cap - 1] = '\0';
            commands++;
        }
    }
    keys[nk] = '\0';
    return commands;
}

void run_serial_console_tests(void)
{
    serial_console_t c;
    serial_console_init(&c);
    char keys[64], cmd[SERIAL_CONSOLE_LINE_MAX];

    CHECK(feed(&c, "1234#x*", keys, cmd, sizeof(cmd)) == 0);
    CHECK(strcmp(keys, "1234#*") == 0);

    /* Digits inside a command line are not keys; CR, LF or CRLF end it. */
    CHECK(feed(&c, "@join atalaia:join:AQID01#\r\n9", keys, cmd, sizeof(cmd)) == 1);
    CHECK(strcmp(cmd, "join atalaia:join:AQID01#") == 0);
    CHECK(strcmp(keys, "9") == 0);
    CHECK(feed(&c, "@joinkey 00ff\n", keys, cmd, sizeof(cmd)) == 1);
    CHECK(strcmp(cmd, "joinkey 00ff") == 0 && keys[0] == '\0');

    /* A line too long for the buffer is dropped whole, and the next one works. */
    static char big[SERIAL_CONSOLE_LINE_MAX + 50];
    big[0] = '@';
    memset(big + 1, '7', sizeof(big) - 3);
    big[sizeof(big) - 2] = '\n';
    big[sizeof(big) - 1] = '\0';
    CHECK(feed(&c, big, keys, cmd, sizeof(cmd)) == 0);
    CHECK(keys[0] == '\0');
    CHECK(feed(&c, "@join x\n5", keys, cmd, sizeof(cmd)) == 1);
    CHECK(strcmp(cmd, "join x") == 0 && strcmp(keys, "5") == 0);

    /* A 448-byte join payload is 611 characters of text: it fits. */
    static char join_line[700];
    join_line[0] = '@';
    memcpy(join_line + 1, "join atalaia:join:", 18);
    memset(join_line + 19, 'A', 598);
    join_line[617] = '\n';
    join_line[618] = '\0';
    CHECK(feed(&c, join_line, keys, cmd, sizeof(cmd)) == 1);
    CHECK(strlen(cmd) == 616);
}
