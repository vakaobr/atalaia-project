/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The box's admin PIN (protocol/adoption.md, decisions AD-28 to AD-32): the
 * one check every place that asks for it goes through (the game picker on
 * the keypad, adoption to another field by card or USB cable).
 *
 * Wrong PINs are counted in NVS and survive a restart. The first
 * ADMIN_PIN_FREE_TRIES in a row cost nothing; after them each further try
 * waits 1, 2, 4, 8 ... minutes (ADMIN_PIN_WAIT_CAP_MIN at most). The count is
 * raised and stored before a PIN is compared, so cutting the power after a
 * wrong guess does not undo it; a right PIN sets it back to 0. The box has no
 * wall clock: after a restart the wait for the stored count starts again in
 * full, never shorter. While a wait runs, a PIN is refused without being
 * compared or counted.
 *
 * No default PIN on a Field Box: a stored PIN that is missing, or too easy to
 * guess (admin_pin_weak), counts as none, and nothing that needs the PIN works
 * until one is set (the setup portal, or "@admin-pin <PIN>" on the USB
 * console while none is set). Bench builds (CONFIG_ATALAIA_SKIP_SETUP) keep
 * 1234 when none is stored, and say so in the log.
 *
 * Platform-free: the shell gives the storage and the clock; the host tests
 * and the host box run it as the box does.
 */
#ifndef ATALAIA_ADMIN_PIN_H
#define ATALAIA_ADMIN_PIN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ADMIN_PIN_MIN          4
#define ADMIN_PIN_MAX          8
#define ADMIN_PIN_FREE_TRIES   5  /* wrong PINs in a row before the waits start */
#define ADMIN_PIN_WAIT_CAP_MIN 60 /* the longest wait, in minutes */
#define ADMIN_PIN_BENCH        "1234"

typedef struct {
    /* The stored count of wrong PINs in a row: 0 and true when none is stored; false when it
     * cannot be read (the box then waits as for ADMIN_PIN_WAIT_CAP_MIN, never less). */
    bool (*load_failures)(void *ctx, uint32_t *failures);
    bool (*store_failures)(void *ctx, uint32_t failures); /* NULL: counted in RAM only */
    /* Keeps a new PIN (NVS); NULL: the PIN cannot be changed here. */
    bool (*store_pin)(void *ctx, const char *pin);
    uint32_t (*now_ms)(void *ctx); /* milliseconds since boot */
    void *ctx;
} admin_pin_ops_t;

typedef enum {
    ADMIN_PIN_OK = 0,
    ADMIN_PIN_WRONG,        /* counted; admin_pin_wait_ms() says whether a wait started */
    ADMIN_PIN_LOCKED,       /* a wait runs: not compared, not counted */
    ADMIN_PIN_NOT_SET,      /* no PIN (or a trivial one) on a Field Box: set one first */
    ADMIN_PIN_STORE_FAILED, /* the count could not be stored: not compared */
} admin_pin_result_t;

typedef struct {
    admin_pin_ops_t ops;
    char pin[ADMIN_PIN_MAX + 1]; /* "" = not set */
    uint32_t failures;
    uint32_t wait_from_ms; /* the current wait's start, and its length */
    uint32_t wait_ms;
} admin_pin_t;

/* "ok", "wrong", "locked", "not_set", "store_failed". */
const char *admin_pin_result_name(admin_pin_result_t r);

/*
 * Why a PIN may not be an admin PIN, or NULL if it may: "length" (not 4-8 characters),
 * "digits" (not only digits), "repeated" (one digit, 0000), "sequence" (each digit one up or
 * one down from the last, wrapping: 1234, 4321, 7890, 0987), "pattern" (two digits taken in
 * turn: 1212, 2525).
 */
const char *admin_pin_weak(const char *pin);

/*
 * The PIN in force: the stored one (NULL: none) if admin_pin_weak accepts it; on a bench build
 * (bench), the stored one whatever it is, or ADMIN_PIN_BENCH. "" when there is none.
 */
void admin_pin_effective(const char *stored, bool bench, char out[ADMIN_PIN_MAX + 1]);

/* Starts the check with the PIN in force (admin_pin_effective) and the stored count; a count of
 * ADMIN_PIN_FREE_TRIES or more starts its whole wait now. */
void admin_pin_init(admin_pin_t *a, const admin_pin_ops_t *ops, const char *pin);

bool admin_pin_is_set(const admin_pin_t *a);

/* The wait for a count of failures: 0 below ADMIN_PIN_FREE_TRIES, then 1, 2, 4 ... minutes up
 * to ADMIN_PIN_WAIT_CAP_MIN. */
uint32_t admin_pin_wait_for(uint32_t failures);

/* What is left of the current wait (0: none), and the same in whole minutes, rounded up. */
uint32_t admin_pin_wait_ms(const admin_pin_t *a);
uint32_t admin_pin_wait_min(const admin_pin_t *a);

/* Checks a typed PIN (counted as above). */
admin_pin_result_t admin_pin_check(admin_pin_t *a, const char *typed);

/*
 * "@admin-pin <new>" while no PIN is set, "@admin-pin <old> <new>" to change it (the old one
 * checked as any other): cmd is the line without the '@'. Returns false if it is not that
 * command; otherwise *reply holds one line for the console.
 */
bool admin_pin_command(admin_pin_t *a, const char *cmd, char *reply, size_t cap);

#endif /* ATALAIA_ADMIN_PIN_H */
