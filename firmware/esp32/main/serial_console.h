/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The serial console's input: keypad keys and command lines.
 *
 *   - 0-9, * and # are keypad keys (the Wokwi emulator and bring-up type
 *     them, since the keypad cannot be pressed from a scenario);
 *   - a line that starts with '@' is a command, collected up to the line
 *     end: "@join atalaia:join:..." (a join text, protocol/join.md) and
 *     "@joinkey <64 hex digits>" (the field join key) and
 *     "@tag <uid hex> [<tag hex>]" (a player tag, protocol/nfc-tag.md).
 *     Digits inside a command line are not keys.
 *
 * Platform-free so the host tests check it.
 */
#ifndef ATALAIA_SERIAL_CONSOLE_H
#define ATALAIA_SERIAL_CONSOLE_H

#include <stdbool.h>
#include <stddef.h>

#define SERIAL_CONSOLE_LINE_MAX 768 /* a 448-byte join payload is 611 characters of text */

typedef struct {
    char line[SERIAL_CONSOLE_LINE_MAX];
    size_t len;
    bool in_command;
    bool overflow;
} serial_console_t;

typedef enum {
    SERIAL_NOTHING = 0,
    SERIAL_KEY,     /* *key holds the key */
    SERIAL_COMMAND, /* a complete command line, without the '@' and the line end */
} serial_input_t;

void serial_console_init(serial_console_t *c);

/*
 * Feeds one byte. Returns SERIAL_KEY with *key set, SERIAL_COMMAND with
 * *command pointing at the line (valid until the next call), or
 * SERIAL_NOTHING. An over-long command line is dropped whole.
 */
serial_input_t serial_console_feed(serial_console_t *c, char byte, char *key, const char **command);

#endif /* ATALAIA_SERIAL_CONSOLE_H */
