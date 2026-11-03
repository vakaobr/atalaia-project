/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The outputs' settings at the box: the picker's screen and the serial console (outputs_admin.h).
 */
#include "outputs_admin.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const uint32_t max_steps[] = {5, 10, 30, 60, 120, 300, 600};
static const char *const named[] = {"siren", "strobe", "smoke", "light", "horn"};

uint32_t outputs_admin_next_max(uint32_t max_s)
{
    for (size_t i = 0; i < sizeof(max_steps) / sizeof(max_steps[0]); i++) {
        if (max_steps[i] > max_s) return max_steps[i];
    }
    return max_steps[0];
}

const char *outputs_admin_next_function(int index, const char *fn)
{
    static char own[16];
    snprintf(own, sizeof(own), "out.%d", index + 1);
    if (fn == NULL || strcmp(fn, own) == 0 || strncmp(fn, "out.", 4) == 0) return named[0];
    for (size_t i = 0; i + 1 < sizeof(named) / sizeof(named[0]); i++) {
        if (strcmp(fn, named[i]) == 0) return named[i + 1];
    }
    return own; /* after horn (or anything else): the output's own number again */
}

void outputs_admin_open(outputs_admin_t *a, outputs_t *o)
{
    memset(a, 0, sizeof(*a));
    a->outputs = o;
    a->open = o != NULL && o->count > 0;
}

bool outputs_admin_active(const outputs_admin_t *a)
{
    return a->open;
}

bool outputs_admin_key(outputs_admin_t *a, char key)
{
    if (!a->open) return false;
    outputs_t *o = a->outputs;
    a->testing = false;
    if (key == '#' || key == '*') {
        a->open = false;
        return false;
    }
    out_settings_t s = o->ch[a->index].set;
    switch (key) {
    case '0': a->index = (a->index + 1) % o->count; break;
    case '1':
        s.enabled = !s.enabled;
        outputs_configure(o, a->index, &s);
        break;
    case '2':
        snprintf(s.function, sizeof(s.function), "%s",
                 outputs_admin_next_function(a->index, s.function));
        outputs_configure(o, a->index, &s);
        break;
    case '3':
        s.max_on_s = outputs_admin_next_max(s.max_on_s);
        outputs_configure(o, a->index, &s);
        break;
    case '5': a->testing = outputs_test(o, a->index) == OUT_OK; break;
    default: break;
    }
    return true;
}

bool outputs_admin_screen(const outputs_admin_t *a, screen_update_t *out)
{
    if (!a->open) return false;
    const out_channel_t *c = &a->outputs->ch[a->index];
    snprintf(out->template_name, sizeof(out->template_name), "start_confirm");
    snprintf(out->data_json, sizeof(out->data_json),
             "{\"output\":%d,\"of\":%d,\"gpio\":%d,\"fn\":\"%s\",\"enabled\":%s,\"max_s\":%lu,"
             "\"testing\":%s}",
             a->index + 1, a->outputs->count, c->gpio, c->id, c->set.enabled ? "true" : "false",
             (unsigned long)c->set.max_on_s, a->testing ? "true" : "false");
    return true;
}

/* ---- The serial console ----------------------------------------------------------------- */

int outputs_admin_args(const char *cmd)
{
    if (cmd == NULL || strncmp(cmd, "output ", 7) != 0) return -1;
    const char *p = cmd + 7;
    while (*p >= '0' && *p <= '9') p++;
    if (*p != ' ') return 1; /* "output <junk>": refused by the command itself */
    p++;
    if (strncmp(p, "enable", 6) == 0 || strncmp(p, "disable", 7) == 0 ||
        strncmp(p, "test", 4) == 0) {
        return 2;
    }
    return 3; /* function <name>, max <s> */
}

static void describe(const outputs_t *o, int i, char *out, size_t cap)
{
    const out_channel_t *c = &o->ch[i];
    snprintf(out, cap, "output %d GPIO %d: %s, %s, at most %lu s, %s", i + 1, c->gpio, c->id,
             c->set.enabled ? "enabled" : "disabled", (unsigned long)c->set.max_on_s,
             c->level ? "on" : "off");
}

bool outputs_admin_command(outputs_t *o, const char *cmd, bool busy, char *reply, size_t cap)
{
    if (cmd == NULL) return false;
    if (strcmp(cmd, "outputs") == 0) {
        if (o == NULL || o->count == 0) {
            snprintf(reply, cap, "outputs: none (a build without CONFIG_ATALAIA_SIMPLE_OUT)");
            return true;
        }
        size_t len = 0;
        reply[0] = '\0';
        for (int i = 0; i < o->count && len + 2 < cap; i++) {
            char line[128];
            describe(o, i, line, sizeof(line));
            len += (size_t)snprintf(reply + len, cap - len, "%s%s", i ? "; " : "", line);
        }
        return true;
    }
    if (strncmp(cmd, "output ", 7) != 0) return false;
    char *end;
    long n = strtol(cmd + 7, &end, 10);
    if (o == NULL || n < 1 || n > o->count || *end != ' ') {
        snprintf(reply, cap,
                 "output: \"@output <1-%d> enable|disable|test|function <name>|max "
                 "<seconds>\"",
                 o != NULL ? o->count : 0);
        return true;
    }
    int i = (int)n - 1;
    const char *what = end + 1;
    if (busy) {
        snprintf(reply, cap, "output %d: not during a game", i + 1);
        return true;
    }
    out_settings_t s = o->ch[i].set;
    out_result_t r;
    if (strcmp(what, "enable") == 0 || strcmp(what, "disable") == 0) {
        s.enabled = what[0] == 'e';
        r = outputs_configure(o, i, &s);
    } else if (strcmp(what, "test") == 0) {
        r = outputs_test(o, i);
    } else if (strncmp(what, "function ", 9) == 0) {
        if (!outputs_function_ok(what + 9)) {
            snprintf(reply, cap,
                     "output %d: the function is siren, strobe, smoke, light, horn or "
                     "out.1-out.9",
                     i + 1);
            return true;
        }
        snprintf(s.function, sizeof(s.function), "%s", what + 9);
        r = outputs_configure(o, i, &s);
    } else if (strncmp(what, "max ", 4) == 0) {
        long max_s = strtol(what + 4, &end, 10);
        if (*end != '\0' || max_s < 1 || max_s > OUT_MAX_ON_MAX_S) {
            snprintf(reply, cap, "output %d: max is 1 to %d seconds", i + 1, OUT_MAX_ON_MAX_S);
            return true;
        }
        s.max_on_s = (uint32_t)max_s;
        r = outputs_configure(o, i, &s);
    } else {
        snprintf(reply, cap, "output %d: enable, disable, test, function <name> or max <seconds>",
                 i + 1);
        return true;
    }
    if (r != OUT_OK) {
        snprintf(reply, cap, "output %d: refused (%s)", i + 1, outputs_result_name(r));
        return true;
    }
    describe(o, i, reply, cap);
    return true;
}
