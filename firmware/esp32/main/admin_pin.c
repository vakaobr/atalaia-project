/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The admin PIN's check, its persistent failure count and its waits (admin_pin.h).
 */
#include "admin_pin.h"

#include <stdio.h>
#include <string.h>

#define MINUTE_MS 60000u
/* A count that cannot be read waits as long as the longest wait (2^6 minutes is past the cap). */
#define UNREADABLE_FAILURES (ADMIN_PIN_FREE_TRIES + 6u)

const char *admin_pin_result_name(admin_pin_result_t r)
{
    switch (r) {
    case ADMIN_PIN_OK: return "ok";
    case ADMIN_PIN_WRONG: return "wrong";
    case ADMIN_PIN_LOCKED: return "locked";
    case ADMIN_PIN_NOT_SET: return "not_set";
    case ADMIN_PIN_STORE_FAILED: return "store_failed";
    }
    return "?";
}

const char *admin_pin_weak(const char *pin)
{
    size_t n = pin != NULL ? strlen(pin) : 0;
    if (n < ADMIN_PIN_MIN || n > ADMIN_PIN_MAX) return "length";
    for (size_t i = 0; i < n; i++) {
        if (pin[i] < '0' || pin[i] > '9') return "digits";
    }
    bool same = true, up = true, down = true, turns = pin[0] != pin[1];
    for (size_t i = 1; i < n; i++) {
        int a = pin[i - 1] - '0', b = pin[i] - '0';
        if (b != a) same = false;
        if (b != (a + 1) % 10) up = false;
        if (b != (a + 9) % 10) down = false;
        if (i >= 2 && pin[i] != pin[i - 2]) turns = false;
    }
    if (same) return "repeated";
    if (up || down) return "sequence";
    if (turns) return "pattern";
    return NULL;
}

void admin_pin_effective(const char *stored, bool bench, char out[ADMIN_PIN_MAX + 1])
{
    out[0] = '\0';
    bool have = stored != NULL && stored[0] != '\0' && strlen(stored) <= ADMIN_PIN_MAX;
    if (bench) {
        snprintf(out, ADMIN_PIN_MAX + 1, "%s", have ? stored : ADMIN_PIN_BENCH);
    } else if (have && admin_pin_weak(stored) == NULL) {
        snprintf(out, ADMIN_PIN_MAX + 1, "%s", stored);
    }
}

uint32_t admin_pin_wait_for(uint32_t failures)
{
    if (failures < ADMIN_PIN_FREE_TRIES) return 0;
    uint32_t steps = failures - ADMIN_PIN_FREE_TRIES; /* 0 -> 1 min, 1 -> 2 min ... */
    uint32_t min = steps >= 6 ? ADMIN_PIN_WAIT_CAP_MIN : (1u << steps);
    if (min > ADMIN_PIN_WAIT_CAP_MIN) min = ADMIN_PIN_WAIT_CAP_MIN;
    return min * MINUTE_MS;
}

static uint32_t now(const admin_pin_t *a)
{
    return a->ops.now_ms != NULL ? a->ops.now_ms(a->ops.ctx) : 0;
}

static void start_wait(admin_pin_t *a)
{
    a->wait_ms = admin_pin_wait_for(a->failures);
    a->wait_from_ms = now(a);
}

void admin_pin_init(admin_pin_t *a, const admin_pin_ops_t *ops, const char *pin)
{
    memset(a, 0, sizeof(*a));
    if (ops != NULL) a->ops = *ops;
    if (pin != NULL && strlen(pin) <= ADMIN_PIN_MAX) snprintf(a->pin, sizeof(a->pin), "%s", pin);
    uint32_t stored = 0;
    if (a->ops.load_failures != NULL && !a->ops.load_failures(a->ops.ctx, &stored)) {
        stored = UNREADABLE_FAILURES;
    }
    a->failures = stored;
    /* No wall clock: a wait that was running when the box went off starts again in full. */
    start_wait(a);
}

bool admin_pin_is_set(const admin_pin_t *a)
{
    return a->pin[0] != '\0';
}

uint32_t admin_pin_wait_ms(const admin_pin_t *a)
{
    if (a->wait_ms == 0) return 0;
    uint32_t gone = now(a) - a->wait_from_ms;
    return gone >= a->wait_ms ? 0 : a->wait_ms - gone;
}

uint32_t admin_pin_wait_min(const admin_pin_t *a)
{
    return (admin_pin_wait_ms(a) + MINUTE_MS - 1u) / MINUTE_MS;
}

/* Constant time over the longest PIN, whatever the lengths. */
static bool same_pin(const char *want, const char *typed)
{
    char a[ADMIN_PIN_MAX + 1] = {0}, b[ADMIN_PIN_MAX + 1] = {0};
    size_t na = strlen(want), nb = strlen(typed);
    if (nb > ADMIN_PIN_MAX) return false;
    memcpy(a, want, na);
    memcpy(b, typed, nb);
    unsigned diff = (unsigned)(na ^ nb);
    for (size_t i = 0; i < ADMIN_PIN_MAX; i++) diff |= (unsigned)(a[i] ^ b[i]);
    memset(a, 0, sizeof(a));
    memset(b, 0, sizeof(b));
    return diff == 0;
}

admin_pin_result_t admin_pin_check(admin_pin_t *a, const char *typed)
{
    if (!admin_pin_is_set(a)) return ADMIN_PIN_NOT_SET;
    if (admin_pin_wait_ms(a) > 0) return ADMIN_PIN_LOCKED;
    /* Counted before it is compared: a power cut after a wrong guess cannot take it back. */
    uint32_t counted = a->failures + 1u;
    if (counted < a->failures) counted = a->failures; /* never wraps */
    if (a->ops.store_failures != NULL && !a->ops.store_failures(a->ops.ctx, counted)) {
        return ADMIN_PIN_STORE_FAILED;
    }
    if (typed != NULL && same_pin(a->pin, typed)) {
        a->failures = 0;
        a->wait_ms = 0;
        if (a->ops.store_failures != NULL) a->ops.store_failures(a->ops.ctx, 0);
        return ADMIN_PIN_OK;
    }
    a->failures = counted;
    start_wait(a);
    return ADMIN_PIN_WRONG;
}

bool admin_pin_command(admin_pin_t *a, const char *cmd, char *reply, size_t cap)
{
    static const char name[] = "admin-pin";
    size_t nl = sizeof(name) - 1;
    if (strncmp(cmd, name, nl) != 0 || (cmd[nl] != ' ' && cmd[nl] != '\0')) return false;
    char first[ADMIN_PIN_MAX + 2] = "", second[ADMIN_PIN_MAX + 2] = "";
    const char *p = cmd + nl;
    int words = 0;
    for (; words < 3; words++) {
        while (*p == ' ') p++;
        if (*p == '\0') break;
        size_t n = strcspn(p, " ");
        if (words < 2) {
            char *dst = words == 0 ? first : second;
            size_t keep = n < ADMIN_PIN_MAX + 1 ? n : ADMIN_PIN_MAX + 1;
            memcpy(dst, p, keep);
            dst[keep] = '\0';
        }
        p += n;
    }
    const char *new_pin = words == 1 ? first : second;
    if (words == 0 || words > 2) {
        snprintf(reply, cap,
                 "admin PIN: \"@admin-pin <new PIN>\", or \"@admin-pin <PIN> <new PIN>\"");
    } else if (words == 1 && admin_pin_is_set(a)) {
        snprintf(reply, cap, "admin PIN: refused (one is set: \"@admin-pin <PIN> <new PIN>\")");
    } else if (admin_pin_weak(new_pin) != NULL) {
        snprintf(
            reply, cap,
            "admin PIN: refused (%s): 4-8 digits, not 1234, 0000, a sequence or a repeated pair",
            admin_pin_weak(new_pin));
    } else {
        admin_pin_result_t r = words == 2 ? admin_pin_check(a, first) : ADMIN_PIN_OK;
        if (r == ADMIN_PIN_LOCKED) {
            snprintf(reply, cap, "admin PIN: locked, try again in %lu min",
                     (unsigned long)admin_pin_wait_min(a));
        } else if (r != ADMIN_PIN_OK) {
            snprintf(reply, cap, "admin PIN: refused (%s)", admin_pin_result_name(r));
        } else if (a->ops.store_pin == NULL || !a->ops.store_pin(a->ops.ctx, new_pin)) {
            snprintf(reply, cap, "admin PIN: not stored");
        } else {
            size_t n = strlen(new_pin); /* 4-8: admin_pin_weak checked it */
            memcpy(a->pin, new_pin, n < ADMIN_PIN_MAX ? n : ADMIN_PIN_MAX);
            a->pin[n < ADMIN_PIN_MAX ? n : ADMIN_PIN_MAX] = '\0';
            snprintf(reply, cap, "admin PIN: set");
        }
    }
    memset(first, 0, sizeof(first));
    memset(second, 0, sizeof(second));
    return true;
}

bool admin_pin_setup_command(admin_pin_t *a, const char *cmd, char *reply, size_t cap, bool *go)
{
    static const char name[] = "setup";
    size_t nl = sizeof(name) - 1;
    *go = false;
    if (strncmp(cmd, name, nl) != 0 || (cmd[nl] != ' ' && cmd[nl] != '\0')) return false;
    const char *p = cmd + nl;
    while (*p == ' ') p++;
    size_t n = strcspn(p, " ");
    const char *rest = p + n;
    while (*rest == ' ') rest++;
    char typed[ADMIN_PIN_MAX + 2];
    snprintf(typed, sizeof(typed), "%.*s", (int)(n < ADMIN_PIN_MAX + 1 ? n : ADMIN_PIN_MAX + 1), p);
    if (*rest != '\0') {
        snprintf(reply, cap, "setup: \"@setup <PIN>\" (\"@setup\" while no admin PIN is set)");
    } else if (!admin_pin_is_set(a)) {
        *go = true;
        snprintf(reply, cap, "setup: no admin PIN is set; restarting into the Wi-Fi setup portal");
    } else if (n == 0) {
        snprintf(reply, cap, "setup: needs the admin PIN: \"@setup <PIN>\"");
    } else {
        admin_pin_result_t r = admin_pin_check(a, typed);
        if (r == ADMIN_PIN_OK) {
            *go = true;
            snprintf(reply, cap, "setup: restarting into the Wi-Fi setup portal");
        } else if (r == ADMIN_PIN_LOCKED) {
            snprintf(reply, cap, "setup: locked, try again in %lu min",
                     (unsigned long)admin_pin_wait_min(a));
        } else {
            snprintf(reply, cap, "setup: refused (%s)", admin_pin_result_name(r));
        }
    }
    memset(typed, 0, sizeof(typed));
    return true;
}

bool admin_pin_gate_serial(admin_pin_t *a, bool open, char *cmd, int args, char *reply, size_t cap)
{
    /* Word starts: the command name, its args, then at most the PIN and one more (too many). */
    const char *w[8];
    int words = 0;
    char *p = cmd;
    while (words < 8) {
        while (*p == ' ') p++;
        if (*p == '\0') break;
        w[words++] = p;
        p += strcspn(p, " ");
    }
    int plain = 1 + args;
    if (words < plain || words > plain + 1) {
        snprintf(reply, cap, "refused: wrong number of words (%d after the name%s)", args,
                 open ? "" : ", then the admin PIN");
        return false;
    }
    if (words == plain) {
        if (open) return true;
        snprintf(reply, cap,
                 "refused: the admin PIN goes last on this line (one is set at the "
                 "Wi-Fi setup, or \"@admin-pin <new PIN>\")");
        return false;
    }
    char typed[ADMIN_PIN_MAX + 2];
    size_t tn = strcspn(w[plain], " ");
    if (tn > ADMIN_PIN_MAX + 1) tn = ADMIN_PIN_MAX + 1; /* longer is wrong anyway */
    memcpy(typed, w[plain], tn);
    typed[tn] = '\0';
    char *cut = cmd + (w[plain] - cmd);
    while (cut > cmd && cut[-1] == ' ') cut--;
    bool ok = true;
    if (!open) {
        admin_pin_result_t r = admin_pin_check(a, typed);
        if (r == ADMIN_PIN_LOCKED) {
            snprintf(reply, cap, "refused: admin PIN locked, try again in %lu min",
                     (unsigned long)admin_pin_wait_min(a));
            ok = false;
        } else if (r != ADMIN_PIN_OK) {
            snprintf(reply, cap, "refused: admin PIN (%s)", admin_pin_result_name(r));
            ok = false;
        }
    }
    memset(typed, 0, sizeof(typed));
    if (ok) *cut = '\0';
    return ok;
}
