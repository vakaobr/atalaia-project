/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The serial console's input: keypad keys and '@' command lines.
 */
#include "serial_console.h"

#include <string.h>

void serial_console_init(serial_console_t *c)
{
    memset(c, 0, sizeof(*c));
}

serial_input_t serial_console_feed(serial_console_t *c, char byte, char *key, const char **command)
{
    if (c->in_command) {
        if (byte == '\r' || byte == '\n') {
            c->in_command = false;
            if (c->overflow) {
                c->overflow = false;
                c->len = 0;
                return SERIAL_NOTHING;
            }
            c->line[c->len] = '\0';
            c->len = 0;
            *command = c->line;
            return SERIAL_COMMAND;
        }
        if (c->len + 1 >= sizeof(c->line)) {
            c->overflow = true;
        } else {
            c->line[c->len++] = byte;
        }
        return SERIAL_NOTHING;
    }
    if (byte == '@') {
        c->in_command = true;
        c->overflow = false;
        c->len = 0;
        return SERIAL_NOTHING;
    }
    if ((byte >= '0' && byte <= '9') || byte == '*' || byte == '#') {
        *key = byte;
        return SERIAL_KEY;
    }
    return SERIAL_NOTHING;
}
