/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The admin PIN (main/admin_pin.c, decisions AD-28 to AD-30): its failure count across a
 * reboot, the waits and their cap, a right PIN setting the count back, the trivial PINs a
 * Field Box refuses, no default PIN outside bench builds, "@admin-pin", and the picker
 * (preset_ui.c) and adoption (adoption.c) going through it.
 */
#include <stdio.h>
#include <string.h>

#include "admin_pin.h"
#include "adoption.h"
#include "check.h"
#include "preset_ui.h"

/* ---- a fake NVS and clock: what survives a "reboot" is nvs ---- */

static struct {
    uint32_t failures;
    bool stored;      /* a count was ever stored */
    bool read_fails;  /* the count cannot be read */
    bool write_fails; /* nor written */
    char pin[16];
    int writes;
} nvs;
static uint32_t clock_ms;

static bool f_load(void *ctx, uint32_t *failures)
{
    (void)ctx;
    if (nvs.read_fails) return false;
    *failures = nvs.stored ? nvs.failures : 0;
    return true;
}

static bool f_store(void *ctx, uint32_t failures)
{
    (void)ctx;
    if (nvs.write_fails) return false;
    nvs.failures = failures;
    nvs.stored = true;
    nvs.writes++;
    return true;
}

static bool f_store_pin(void *ctx, const char *pin)
{
    (void)ctx;
    snprintf(nvs.pin, sizeof(nvs.pin), "%s", pin);
    return true;
}

static uint32_t f_now(void *ctx)
{
    (void)ctx;
    return clock_ms;
}

static const admin_pin_ops_t OPS = {f_load, f_store, f_store_pin, f_now, NULL};

/* Adoption stores whatever it is given. */
static bool a_store(void *ctx, const uint8_t key[ADOPTION_KEY_SIZE], const char *name)
{
    (void)ctx;
    (void)key;
    (void)name;
    return true;
}

static const adoption_ops_t AOPS = {NULL, a_store, NULL, NULL, NULL};

/* The box starts (again): its clock from 0, the count from "NVS". */
static void boot(admin_pin_t *a, const char *pin)
{
    clock_ms = 1000;
    admin_pin_init(a, &OPS, pin);
}

#define MIN_MS 60000u

static void test_weak_pins(void)
{
    static const char *const weak[][2] = {
        {"1234", "sequence"}, {"0000", "repeated"},  {"1111", "repeated"}, {"4321", "sequence"},
        {"0123", "sequence"}, {"7890", "sequence"},  {"9876", "sequence"}, {"12345678", "sequence"},
        {"1212", "pattern"},  {"252525", "pattern"}, {"123", "length"},    {"123456789", "length"},
        {"12a4", "digits"},   {"", "length"},
    };
    for (size_t i = 0; i < sizeof(weak) / sizeof(weak[0]); i++) {
        const char *why = admin_pin_weak(weak[i][0]);
        CHECK(why != NULL && strcmp(why, weak[i][1]) == 0);
    }
    CHECK(admin_pin_weak(NULL) != NULL);
    static const char *const fine[] = {"2580", "1357", "8016", "4711", "90210", "13371337"};
    for (size_t i = 0; i < sizeof(fine) / sizeof(fine[0]); i++)
        CHECK(admin_pin_weak(fine[i]) == NULL);
}

static void test_no_default_pin(void)
{
    char pin[ADMIN_PIN_MAX + 1];
    /* A Field Box: no PIN, or a trivial one, is none at all. */
    admin_pin_effective(NULL, false, pin);
    CHECK(pin[0] == '\0');
    admin_pin_effective("1234", false, pin);
    CHECK(pin[0] == '\0');
    admin_pin_effective("4711", false, pin);
    CHECK(strcmp(pin, "4711") == 0);
    /* A bench build: 1234 when none is stored, and whatever is stored. */
    admin_pin_effective(NULL, true, pin);
    CHECK(strcmp(pin, ADMIN_PIN_BENCH) == 0);
    admin_pin_effective("0000", true, pin);
    CHECK(strcmp(pin, "0000") == 0);

    admin_pin_t a;
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "");
    CHECK(!admin_pin_is_set(&a));
    CHECK(admin_pin_check(&a, "1234") == ADMIN_PIN_NOT_SET && nvs.writes == 0);
    /* The picker says so, and lets nothing through. */
    preset_ui_t ui;
    preset_ui_init(&ui, NULL, 3);
    preset_ui_set_guard(&ui, &a);
    preset_ui_handle_key(&ui, '1');
    preset_ui_handle_key(&ui, '#');
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY && ui.no_pin && !ui.pin_error);
    screen_update_t su;
    CHECK(preset_ui_screen(&ui, NULL, 0, &su) && strstr(su.data_json, "\"no_pin\":true") != NULL);
    /* Adoption to another field: refused, "no_pin". */
    adoption_t ad;
    adoption_init(&ad, &AOPS, NULL);
    adoption_set_pin(&ad, &a);
    uint8_t mine[32] = {1}, other[32] = {2};
    adoption_restore(&ad, mine, "Campo");
    CHECK(adoption_offer(&ad, other, "Outro", "1234") == ADOPT_NO_PIN);
    CHECK(strcmp(adopt_result_name(ADOPT_NO_PIN), "no_pin") == 0);
}

static void test_backoff_and_reboot(void)
{
    admin_pin_t a;
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "4711");
    CHECK(admin_pin_wait_ms(&a) == 0);
    /* Four wrong PINs cost nothing; the fifth starts a 1-minute wait. */
    for (int i = 1; i <= 4; i++) {
        CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG);
        CHECK(nvs.failures == (uint32_t)i && admin_pin_wait_ms(&a) == 0);
    }
    CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG && nvs.failures == 5);
    CHECK(admin_pin_wait_ms(&a) == MIN_MS && admin_pin_wait_min(&a) == 1);
    /* During the wait even the right PIN is refused, not compared and not counted. */
    int writes = nvs.writes;
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_LOCKED && nvs.writes == writes);
    clock_ms += MIN_MS - 1;
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_LOCKED && admin_pin_wait_min(&a) == 1);
    clock_ms += 1;
    /* Then 2, 4, 8, 16, 32 minutes, and 60 at most from then on. */
    static const uint32_t waits[] = {2, 4, 8, 16, 32, 60, 60, 60};
    for (size_t i = 0; i < sizeof(waits) / sizeof(waits[0]); i++) {
        CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG);
        CHECK(admin_pin_wait_ms(&a) == waits[i] * MIN_MS);
        clock_ms += waits[i] * MIN_MS;
    }
    CHECK(admin_pin_wait_for(4) == 0 && admin_pin_wait_for(5) == MIN_MS);
    CHECK(admin_pin_wait_for(0xFFFFFFFFu) == 60 * MIN_MS);
    uint32_t count = nvs.failures;
    CHECK(count == 13);

    /* A wrong guess, then the power is cut: the count was stored before the PIN was compared. */
    CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG && nvs.failures == count + 1);
    clock_ms += 59 * MIN_MS; /* 59 of its 60 minutes gone */
    /* The reboot: no wall clock, so the whole wait for that count starts again, never shorter. */
    boot(&a, "4711");
    CHECK(a.failures == count + 1 && admin_pin_wait_ms(&a) == 60 * MIN_MS);
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_LOCKED);
    clock_ms += 60 * MIN_MS;
    /* The right PIN: in, and the count back to 0, also after the next reboot. */
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_OK && nvs.failures == 0 && a.failures == 0);
    boot(&a, "4711");
    CHECK(admin_pin_wait_ms(&a) == 0);
    for (int i = 0; i < 4; i++) CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG);
    CHECK(admin_pin_wait_ms(&a) == 0); /* the five free tries again */

    /* Four wrong before a reboot and one after still make five: the count is NVS's. */
    boot(&a, "4711");
    CHECK(a.failures == 4 && admin_pin_wait_ms(&a) == 0);
    CHECK(admin_pin_check(&a, "0000") == ADMIN_PIN_WRONG && admin_pin_wait_min(&a) == 1);

    /* A count that cannot be stored: nothing is compared. One that cannot be read: the longest
     * wait. */
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "4711");
    nvs.write_fails = true;
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_STORE_FAILED);
    nvs.write_fails = false;
    nvs.read_fails = true;
    boot(&a, "4711");
    CHECK(admin_pin_wait_ms(&a) == 60 * MIN_MS);
}

static void test_everywhere_the_pin_is_asked(void)
{
    admin_pin_t a;
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "4711");
    /* The picker: wrong PINs count, and once the wait starts it says how long. */
    preset_ui_t ui;
    preset_ui_init(&ui, NULL, 3);
    preset_ui_set_guard(&ui, &a);
    for (int i = 0; i < 4; i++) {
        preset_ui_handle_key(&ui, '9');
        preset_ui_handle_key(&ui, '#');
        CHECK(ui.pin_error && ui.locked_min == 0);
    }
    /* Adoption by a card or the cable counts on the same check: the fifth wrong PIN locks both. */
    adoption_t ad;
    adoption_init(&ad, &AOPS, NULL);
    adoption_set_pin(&ad, &a);
    uint8_t mine[32] = {1}, other[32] = {2};
    adoption_restore(&ad, mine, "Campo");
    CHECK(adoption_offer(&ad, other, "Outro", "0000") == ADOPT_LOCKED && nvs.failures == 5);
    CHECK(adoption_offer(&ad, other, "Outro", "4711") == ADOPT_LOCKED);
    preset_ui_handle_key(&ui, '4');
    preset_ui_handle_key(&ui, '#');
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY && ui.locked_min == 1 &&
          !ui.pin_error);
    screen_update_t su;
    CHECK(preset_ui_screen(&ui, NULL, 0, &su) && strstr(su.data_json, "\"locked_min\":1") != NULL);
    char reply[ADOPTION_REPLY_MAX];
    CHECK(adoption_command(&ad, "adopt-info", NULL, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"locked\":true,\"locked_min\":1,\"pin_set\":true") != NULL);
    clock_ms += MIN_MS;
    CHECK(adoption_offer(&ad, other, "Outro", "4711") == ADOPT_READOPTED && nvs.failures == 0);
    const char *keys = "4711#";
    for (const char *k = keys; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);
}

static void test_admin_pin_command(void)
{
    admin_pin_t a;
    char reply[160];
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "");
    CHECK(!admin_pin_command(&a, "adopt-info", reply, sizeof(reply)));
    CHECK(!admin_pin_command(&a, "admin-pins 4711", reply, sizeof(reply)));
    /* None set: one word sets it, unless it is too easy to guess. */
    CHECK(admin_pin_command(&a, "admin-pin 1234", reply, sizeof(reply)));
    CHECK(strstr(reply, "refused (sequence)") != NULL && !admin_pin_is_set(&a));
    CHECK(admin_pin_command(&a, "admin-pin 4711", reply, sizeof(reply)));
    CHECK(strcmp(reply, "admin PIN: set") == 0 && strcmp(nvs.pin, "4711") == 0);
    CHECK(admin_pin_check(&a, "4711") == ADMIN_PIN_OK);
    /* Set: one word is refused; the old PIN, checked as any other, changes it. */
    CHECK(admin_pin_command(&a, "admin-pin 8016", reply, sizeof(reply)));
    CHECK(strstr(reply, "refused (one is set") != NULL && strcmp(nvs.pin, "4711") == 0);
    CHECK(admin_pin_command(&a, "admin-pin 0000 8016", reply, sizeof(reply)));
    CHECK(strcmp(reply, "admin PIN: refused (wrong)") == 0 && nvs.failures == 1);
    CHECK(admin_pin_command(&a, "admin-pin 4711 8016", reply, sizeof(reply)));
    CHECK(strcmp(reply, "admin PIN: set") == 0 && strcmp(nvs.pin, "8016") == 0);
    CHECK(admin_pin_check(&a, "8016") == ADMIN_PIN_OK);
    CHECK(admin_pin_command(&a, "admin-pin", reply, sizeof(reply)));
    CHECK(strstr(reply, "\"@admin-pin <new PIN>\"") != NULL);
    CHECK(admin_pin_command(&a, "admin-pin 1 2 3", reply, sizeof(reply)));
    CHECK(strstr(reply, "\"@admin-pin <new PIN>\"") != NULL);
}

/* "@setup": back into the Wi-Fi setup portal, with the admin PIN as every other place that asks
 * for it; with no PIN set there is nothing to ask. */
static void test_setup_command(void)
{
    admin_pin_t a;
    char reply[160];
    bool go = true;
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "4711");
    CHECK(!admin_pin_setup_command(&a, "adopt-info", reply, sizeof(reply), &go) && !go);
    CHECK(!admin_pin_setup_command(&a, "setups", reply, sizeof(reply), &go) && !go);
    /* Set: no PIN, a wrong one (counted) and too many words go nowhere. */
    CHECK(admin_pin_setup_command(&a, "setup", reply, sizeof(reply), &go) && !go);
    CHECK(strstr(reply, "needs the admin PIN") != NULL);
    CHECK(admin_pin_setup_command(&a, "setup 0000", reply, sizeof(reply), &go) && !go);
    CHECK(strcmp(reply, "setup: refused (wrong)") == 0 && nvs.failures == 1);
    CHECK(admin_pin_setup_command(&a, "setup 4711 now", reply, sizeof(reply), &go) && !go);
    CHECK(strstr(reply, "@setup <PIN>") != NULL && nvs.failures == 1);
    /* The right PIN: go, and the count is back to 0. */
    CHECK(admin_pin_setup_command(&a, "setup 4711", reply, sizeof(reply), &go) && go);
    CHECK(strstr(reply, "restarting into the Wi-Fi setup portal") != NULL && nvs.failures == 0);
    /* Five wrong PINs in a row start the waits: even the right one is then refused, unseen. */
    for (int i = 0; i < ADMIN_PIN_FREE_TRIES; i++) {
        CHECK(admin_pin_setup_command(&a, "setup 0000", reply, sizeof(reply), &go) && !go);
    }
    CHECK(admin_pin_setup_command(&a, "setup 4711", reply, sizeof(reply), &go) && !go);
    CHECK(strstr(reply, "locked, try again in") != NULL);

    /* No PIN set: "@setup" is enough, as "@admin-pin" is. */
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "");
    CHECK(admin_pin_setup_command(&a, "setup", reply, sizeof(reply), &go) && go);
    CHECK(strstr(reply, "no admin PIN is set") != NULL);
}

/* Decision SR-40: "@joinkey" and "@update" need the admin PIN in a release build, not in a bench
 * one. */
static void test_serial_gate(void)
{
    admin_pin_t a;
    char reply[160], line[96];
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "4711");

    /* Release: the PIN goes last, is checked and is cut off. */
    snprintf(line, sizeof(line), "joinkey 00ff 4711");
    CHECK(admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    CHECK(strcmp(line, "joinkey 00ff") == 0);
    snprintf(line, sizeof(line), "update 0.3.2 rel1  4711");
    CHECK(admin_pin_gate_serial(&a, false, line, 2, reply, sizeof(reply)));
    CHECK(strcmp(line, "update 0.3.2 rel1") == 0);
    /* Without it, with a wrong one, or with extra words: refused, the line is not for the box. */
    snprintf(line, sizeof(line), "joinkey 00ff");
    CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    CHECK(strstr(reply, "admin PIN goes last") != NULL);
    snprintf(line, sizeof(line), "joinkey 00ff 0000");
    CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    CHECK(strstr(reply, "wrong") != NULL && nvs.failures == 1);
    snprintf(line, sizeof(line), "joinkey 00ff 4711 extra");
    CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    snprintf(line, sizeof(line), "update 0.3.2 4711");
    CHECK(!admin_pin_gate_serial(&a, false, line, 2, reply, sizeof(reply)));
    /* A wrong PIN counts like any other: the fifth starts the wait, and then the right one is
     * refused. */
    for (int i = 0; i < 4; i++) {
        snprintf(line, sizeof(line), "joinkey 00ff 0000");
        CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    }
    snprintf(line, sizeof(line), "joinkey 00ff 4711");
    CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    CHECK(strstr(reply, "locked, try again in") != NULL);

    /* No PIN set: nothing passes. */
    memset(&nvs, 0, sizeof(nvs));
    boot(&a, "");
    snprintf(line, sizeof(line), "joinkey 00ff 4711");
    CHECK(!admin_pin_gate_serial(&a, false, line, 1, reply, sizeof(reply)));
    CHECK(strstr(reply, "not_set") != NULL);

    /* Bench: open as before, and a PIN word is cut off unchecked. */
    snprintf(line, sizeof(line), "joinkey 00ff");
    CHECK(admin_pin_gate_serial(&a, true, line, 1, reply, sizeof(reply)));
    CHECK(strcmp(line, "joinkey 00ff") == 0);
    snprintf(line, sizeof(line), "update 0.3.2 rel1 whatever");
    CHECK(admin_pin_gate_serial(&a, true, line, 2, reply, sizeof(reply)));
    CHECK(strcmp(line, "update 0.3.2 rel1") == 0);
    snprintf(line, sizeof(line), "update 0.3.2");
    CHECK(!admin_pin_gate_serial(&a, true, line, 2, reply, sizeof(reply)));
}

void run_admin_pin_tests(void)
{
    test_serial_gate();
    test_setup_command();
    test_weak_pins();
    test_no_default_pin();
    test_backoff_and_reboot();
    test_everywhere_the_pin_is_asked();
    test_admin_pin_command();
}
