/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Adoption (main/adoption.c, protocol/adoption.md): the field card against the
 * shared vectors (protocol/vectors/field_card.json, also checked by the Python
 * codec), the adoption rules, the PIN on the keypad and the console commands.
 */
#include <stdio.h>
#include <string.h>

#include "adoption.h"
#include "atalaia/join.h"
#include "check.h"
#include "field_card_vectors.h"

/* ---- a fake shell ------------------------------------------------------ */

static struct {
    bool busy;
    bool store_fails;
    int stores;
    uint8_t key[32];
    char name[64];
    char tmpl[32];
    char data[256];
    int screens;
    char log[160];
} sh;

static bool f_busy(void *ctx)
{
    (void)ctx;
    return sh.busy;
}

static bool f_store(void *ctx, const uint8_t key[32], const char *name)
{
    (void)ctx;
    if (sh.store_fails) return false;
    sh.stores++;
    memcpy(sh.key, key, 32);
    snprintf(sh.name, sizeof(sh.name), "%s", name);
    return true;
}

static void f_screen(void *ctx, const char *tmpl, const char *data)
{
    (void)ctx;
    snprintf(sh.tmpl, sizeof(sh.tmpl), "%s", tmpl);
    snprintf(sh.data, sizeof(sh.data), "%s", data);
    sh.screens++;
}

static void f_log(void *ctx, const char *line)
{
    (void)ctx;
    snprintf(sh.log, sizeof(sh.log), "%s", line);
}

static const adoption_ops_t OPS = {f_busy, f_store, f_screen, f_log, NULL};

static void fresh(adoption_t *a)
{
    memset(&sh, 0, sizeof(sh));
    adoption_init(a, &OPS, "4321");
}

static void key_of(uint8_t key[32], uint8_t first)
{
    for (int i = 0; i < 32; i++) key[i] = (uint8_t)(first + i);
}

/* ---- the field card ------------------------------------------------------ */

static void test_card_vectors(void)
{
    CHECK(FIELD_CARD_VECTOR_COUNT >= 4);
    CHECK(FIELD_CARD_BAD_VECTOR_COUNT >= 18);
    for (size_t i = 0; i < FIELD_CARD_VECTOR_COUNT; i++) {
        const field_card_vector_t *v = &field_card_vectors[i];
        adoption_card_t card;
        CHECK(adoption_card_decode(v->payload, v->payload_len, &card) == ADOPTION_CARD_OK);
        CHECK(memcmp(card.key, v->key, 32) == 0);
        CHECK(strcmp(card.name, v->field_name) == 0);
        uint8_t buf[ADOPTION_CARD_MAX];
        CHECK(adoption_card_encode(&card, buf, sizeof(buf)) == v->payload_len);
        CHECK(memcmp(buf, v->payload, v->payload_len) == 0);
        CHECK(adoption_card_encode(&card, buf, v->payload_len - 1) == 0);
        char fp[ADOPTION_FP_SIZE];
        adoption_fingerprint(v->key, fp);
        CHECK(strcmp(fp, v->fingerprint) == 0);
        const uint8_t *p = NULL;
        CHECK(adoption_card_from_ndef_tag(v->ndef_tag, v->ndef_tag_len, &p) == v->payload_len);
        CHECK(p != NULL && memcmp(p, v->payload, v->payload_len) == 0);
        /* A join card reader finds no join payload on a field card. */
        const uint8_t *j = NULL;
        CHECK(atalaia_join_from_ndef_tag(v->ndef_tag, v->ndef_tag_len, &j) == 0);
        /* The core's NDEF writer makes the same bytes. */
        uint8_t mem[128];
        size_t n = atalaia_ndef_write_mime(ADOPTION_NDEF_TYPE, v->payload, v->payload_len, mem,
                                           sizeof(mem));
        CHECK(n == v->ndef_tag_len && memcmp(mem, v->ndef_tag, n) == 0);
    }
    for (size_t i = 0; i < FIELD_CARD_BAD_VECTOR_COUNT; i++) {
        const field_card_bad_vector_t *v = &field_card_bad_vectors[i];
        adoption_card_t card;
        adoption_card_result_t r = adoption_card_decode(v->payload, v->payload_len, &card);
        if (strcmp(adoption_card_result_name(r), v->reason) != 0) {
            fprintf(stderr, "field card %s: %s, want %s\n", v->name, adoption_card_result_name(r),
                    v->reason);
        }
        CHECK(strcmp(adoption_card_result_name(r), v->reason) == 0);
    }
}

static void test_join_card_is_no_field_card(void)
{
    uint8_t payload[40] = {1}, mem[128];
    size_t n = atalaia_join_to_ndef_tag(payload, sizeof(payload), mem, sizeof(mem));
    CHECK(n > 0);
    const uint8_t *p = NULL;
    CHECK(adoption_card_from_ndef_tag(mem, n, &p) == 0);
    adoption_t a;
    fresh(&a);
    adopt_result_t r = ADOPT_ADOPTED;
    CHECK(!adoption_tap(&a, mem, n, 0, &r)); /* not ours: the shell reads it as a join card */
    CHECK(sh.screens == 0);
}

static void test_names(void)
{
    CHECK(adoption_name_ok("", 0));
    const char *utf8 = "Campo \xc3\x89vora \xe2\x80\x94 \xf0\x9f\x8c\xb2";
    CHECK(adoption_name_ok(utf8, strlen(utf8)));
    CHECK(!adoption_name_ok("a\"b", 3));
    CHECK(!adoption_name_ok("a\\b", 3));
    CHECK(!adoption_name_ok("a\tb", 3));
    CHECK(!adoption_name_ok("\xc3", 1));             /* cut short */
    CHECK(!adoption_name_ok("\xe0\x80\xaf", 3));     /* overlong */
    CHECK(!adoption_name_ok("\xed\xa0\x80", 3));     /* surrogate */
    CHECK(!adoption_name_ok("\xf4\x90\x80\x80", 4)); /* beyond U+10FFFF */
    CHECK(!adoption_name_ok("\x80", 1));
    char long_name[50];
    memset(long_name, 'A', 49);
    long_name[49] = '\0';
    CHECK(!adoption_name_ok(long_name, 49));
    CHECK(adoption_name_ok(long_name, 48));
}

/* ---- the rules ----------------------------------------------------------- */

static void test_rules(void)
{
    adoption_t a;
    uint8_t mine[32], other[32];
    key_of(mine, 0);
    key_of(other, 1);
    fresh(&a);
    CHECK(!a.adopted);
    CHECK(adoption_offer(&a, mine, "Campo", NULL) == ADOPT_ADOPTED);
    CHECK(a.adopted && sh.stores == 1 && memcmp(sh.key, mine, 32) == 0);
    CHECK(strcmp(a.name, "Campo") == 0 && strcmp(a.fingerprint, "604A-0A95") == 0);
    CHECK(adoption_offer(&a, mine, "Campo", NULL) == ADOPT_SAME && sh.stores == 1);
    CHECK(adoption_offer(&a, mine, "", NULL) == ADOPT_SAME && strcmp(a.name, "Campo") == 0);
    CHECK(adoption_offer(&a, mine, "Campo Novo", NULL) == ADOPT_SAME && sh.stores == 2);
    CHECK(strcmp(a.name, "Campo Novo") == 0);
    /* Another field: only with the admin PIN. */
    CHECK(adoption_offer(&a, other, "Outro", NULL) == ADOPT_NEED_PIN);
    CHECK(adoption_offer(&a, other, "Outro", "") == ADOPT_NEED_PIN);
    CHECK(adoption_offer(&a, other, "Outro", "1234") == ADOPT_BAD_PIN);
    CHECK(adoption_offer(&a, other, "Outro", "43210") == ADOPT_BAD_PIN); /* longer, same start */
    CHECK(adoption_offer(&a, other, "Outro", "432") == ADOPT_BAD_PIN);
    CHECK(memcmp(a.key, mine, 32) == 0 && sh.stores == 2);
    CHECK(adoption_offer(&a, other, "Outro", "4321") == ADOPT_READOPTED);
    CHECK(memcmp(a.key, other, 32) == 0 && strcmp(a.name, "Outro") == 0 && a.pin->failures == 0);
    /* Five wrong PINs in a row start a wait, the right one refused during it (admin_pin.h: the
     * waits and the count across a reboot are test_admin_pin.c's). */
    for (int i = 0; i < ADOPTION_PIN_TRIES - 1; i++) {
        CHECK(adoption_offer(&a, mine, "", "0000") == ADOPT_BAD_PIN);
    }
    CHECK(adoption_offer(&a, mine, "", "0000") == ADOPT_LOCKED);
    CHECK(adoption_offer(&a, mine, "", "4321") == ADOPT_LOCKED);
    CHECK(adoption_offer(&a, other, "", NULL) == ADOPT_SAME); /* its own field still works */
    /* A game joined, a failing store, a name not allowed. */
    fresh(&a);
    sh.busy = true;
    CHECK(adoption_offer(&a, mine, "", NULL) == ADOPT_BUSY && !a.adopted);
    sh.busy = false;
    sh.store_fails = true;
    CHECK(adoption_offer(&a, mine, "", NULL) == ADOPT_STORE_FAILED && !a.adopted);
    sh.store_fails = false;
    CHECK(adoption_offer(&a, mine, "a\"b", NULL) == ADOPT_BAD_KEY && !a.adopted);
    /* A box restored from NVS is adopted; with no admin PIN set nothing moves it (AD-29). */
    adoption_init(&a, &OPS, "");
    adoption_restore(&a, mine, "Campo");
    CHECK(a.adopted && strcmp(a.fingerprint, "604A-0A95") == 0);
    CHECK(adoption_offer(&a, other, "", "") == ADOPT_NO_PIN);
    CHECK(adoption_offer(&a, other, "", "1234") == ADOPT_NO_PIN);
}

/* ---- a card tapped, the PIN on the keypad -------------------------------- */

static size_t card_tag(const uint8_t key[32], const char *name, uint8_t *mem, size_t cap)
{
    adoption_card_t card;
    memcpy(card.key, key, 32);
    snprintf(card.name, sizeof(card.name), "%s", name);
    uint8_t payload[ADOPTION_CARD_MAX];
    size_t n = adoption_card_encode(&card, payload, sizeof(payload));
    return atalaia_ndef_write_mime(ADOPTION_NDEF_TYPE, payload, n, mem, cap);
}

static void test_tap_and_pin(void)
{
    adoption_t a;
    uint8_t mine[32], other[32], mem[128];
    key_of(mine, 0);
    key_of(other, 1);
    fresh(&a);
    adopt_result_t r;
    size_t n = card_tag(mine, "Campo", mem, sizeof(mem));
    CHECK(adoption_tap(&a, mem, n, 1000, &r) && r == ADOPT_ADOPTED);
    CHECK(strcmp(sh.tmpl, "status") == 0);
    CHECK(strstr(sh.data, "\"title\":\"Adopted\"") && strstr(sh.data, "\"field\":\"Campo\"") &&
          strstr(sh.data, "\"fingerprint\":\"604A-0A95\""));
    CHECK(strstr(sh.log, "adoption (card): adopted, field 604A-0A95") != NULL);
    CHECK(adoption_active(&a));
    CHECK(!adoption_tick(&a, 1000 + ADOPTION_SCREEN_MS - 1));
    CHECK(adoption_tick(&a, 1000 + ADOPTION_SCREEN_MS));
    CHECK(!adoption_active(&a) && !adoption_tick(&a, 9000));

    /* Another field's card waits for the PIN. */
    n = card_tag(other, "Outro", mem, sizeof(mem));
    CHECK(adoption_tap(&a, mem, n, 10000, &r) && r == ADOPT_NEED_PIN);
    CHECK(a.pending && strcmp(sh.tmpl, "pin_entry") == 0 && strstr(sh.data, "\"digits\":0"));
    CHECK(adoption_key(&a, '1', 10100) && strstr(sh.data, "\"digits\":1"));
    CHECK(adoption_key(&a, '2', 10200) && adoption_key(&a, '*', 10300) &&
          strstr(sh.data, "\"digits\":1"));
    CHECK(adoption_key(&a, '#', 10400)); /* "1": wrong */
    CHECK(a.pending && strstr(sh.data, "\"error\":true") && strstr(sh.data, "\"digits\":0"));
    const char *pin = "4321";
    for (const char *p = pin; *p; p++) CHECK(adoption_key(&a, *p, 10500));
    CHECK(adoption_key(&a, '#', 10600));
    CHECK(!a.pending && memcmp(a.key, other, 32) == 0 && strcmp(a.name, "Outro") == 0);
    CHECK(strstr(sh.data, "\"title\":\"Adopted\"") && strstr(sh.data, "\"field\":\"Outro\""));
    CHECK(adoption_key(&a, '5', 10700)); /* any key closes the result */
    CHECK(adoption_tick(&a, 10701) && !adoption_active(&a));
    CHECK(!adoption_key(&a, '5', 10800)); /* then keys are the shell's again */

    /* '*' on an empty PIN cancels; so does a minute without a key. */
    n = card_tag(mine, "Campo", mem, sizeof(mem));
    CHECK(adoption_tap(&a, mem, n, 20000, &r) && r == ADOPT_NEED_PIN);
    CHECK(adoption_key(&a, '*', 20100) && !a.pending);
    CHECK(adoption_tick(&a, 20101) && memcmp(a.key, other, 32) == 0);
    CHECK(adoption_tap(&a, mem, n, 30000, &r) && r == ADOPT_NEED_PIN);
    CHECK(adoption_key(&a, '9', 30000 + ADOPTION_PIN_WAIT_MS - 10)); /* a key keeps it waiting */
    CHECK(!adoption_tick(&a, 30000 + ADOPTION_PIN_WAIT_MS));
    CHECK(adoption_tick(&a, 30000 + 2 * ADOPTION_PIN_WAIT_MS) && !a.pending);
    CHECK(strstr(sh.log, "cancelled") != NULL);

    /* A damaged card is shown and logged; with a game joined the game's screen stays. */
    n = card_tag(mine, "Campo", mem, sizeof(mem));
    mem[n - 3] ^= 1; /* in the check */
    CHECK(adoption_tap(&a, mem, n, 40000, &r) && r == ADOPT_BAD_CARD);
    CHECK(strstr(sh.data, "Bad field card") && strstr(sh.log, "(check)"));
    adoption_tick(&a, 50000);
    sh.busy = true;
    int screens = sh.screens;
    n = card_tag(mine, "Campo", mem, sizeof(mem));
    CHECK(adoption_tap(&a, mem, n, 60000, &r) && r == ADOPT_BUSY && sh.screens == screens);
    CHECK(!adoption_active(&a));
}

/* ---- the console commands ------------------------------------------------ */

static const char MINE_HEX[] = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
static const char OTHER_HEX[] = "0102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F20";

static void test_commands(void)
{
    adoption_t a;
    char reply[ADOPTION_REPLY_MAX], cmd[200];
    adoption_identity_t id = {"box \"7\"", "24:58:7C:DA:11:F0", "0.4.0"};
    fresh(&a);
    CHECK(!adoption_command(&a, "join atalaia:join:x", &id, 0, reply, sizeof(reply)));
    CHECK(!adoption_command(&a, "adoption", &id, 0, reply, sizeof(reply)));
    CHECK(adoption_command(&a, "adopt-info", &id, 0, reply, sizeof(reply)));
    CHECK(strcmp(reply, "ATALAIA-ADOPT {\"v\":1,\"kind\":\"info\",\"name\":\"box \\\"7\\\"\","
                        "\"mac\":\"24:58:7C:DA:11:F0\",\"fw\":\"0.4.0\",\"state\":\"unadopted\","
                        "\"field\":\"\",\"field_name\":\"\",\"busy\":false,\"locked\":false,"
                        "\"locked_min\":0,\"pin_set\":true}") == 0);

    snprintf(cmd, sizeof(cmd), "adopt %s - Campo da Atalaia", MINE_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strcmp(reply, "ATALAIA-ADOPT {\"v\":1,\"kind\":\"result\",\"result\":\"adopted\","
                        "\"state\":\"adopted\",\"field\":\"604A-0A95\","
                        "\"field_name\":\"Campo da Atalaia\"}") == 0);
    CHECK(strstr(sh.log, "adoption (usb): adopted") != NULL);
    CHECK(strcmp(sh.tmpl, "status") == 0);

    /* Another field without, with a wrong and with the right PIN. */
    snprintf(cmd, sizeof(cmd), "adopt %s", OTHER_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"result\":\"need_pin\"") && strstr(reply, "\"field\":\"604A-0A95\""));
    snprintf(cmd, sizeof(cmd), "adopt %s 1111 Outro", OTHER_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"result\":\"bad_pin\"") != NULL);
    snprintf(cmd, sizeof(cmd), "joinkey %s", OTHER_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strncmp(reply, "join key: refused (adopted to another field", 43) == 0);
    snprintf(cmd, sizeof(cmd), "adopt %s 4321 Outro", OTHER_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"result\":\"readopted\"") && strstr(reply, "\"field_name\":\"Outro\""));
    snprintf(cmd, sizeof(cmd), "joinkey %s", OTHER_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strcmp(reply, "join key: stored") == 0);

    /* Malformed lines. */
    const char *bad[] = {"adopt ",
                         "adopt 0011",
                         "adopt %sz",
                         "adopt %s  Campo",
                         "adopt %s 123456789 Campo",
                         "adopt %s - a\"b",
                         "joinkey %s extra"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        snprintf(cmd, sizeof(cmd), bad[i], MINE_HEX);
        CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
        CHECK(strstr(reply, "bad_key") != NULL || strstr(reply, "refused (64 hex") != NULL);
    }
    /* A game joined. */
    sh.busy = true;
    snprintf(cmd, sizeof(cmd), "adopt %s 4321", MINE_HEX);
    CHECK(adoption_command(&a, cmd, &id, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"result\":\"busy\"") != NULL);
    CHECK(adoption_command(&a, "adopt-info", &id, 0, reply, sizeof(reply)));
    CHECK(strstr(reply, "\"busy\":true") && strstr(reply, "\"state\":\"adopted\""));
}

/* The admin menu's "Adopt to another field" (decision PKB-4): the pairing code may move an adopted
 * box without the PIN only while the menu armed it, once; nothing else skips the PIN. */
static void test_move_armed(void)
{
    adoption_t a;
    uint8_t mine[32], other[32], third[32];
    key_of(mine, 0);
    key_of(other, 1);
    key_of(third, 2);
    fresh(&a);
    /* Not adopted, or no admin PIN: nothing to arm. */
    CHECK(!adoption_allow_move(&a, true) && !a.move_armed);
    CHECK(adoption_offer(&a, mine, "Campo", NULL) == ADOPT_ADOPTED);
    {
        adoption_t nopin;
        memset(&sh, 0, sizeof(sh));
        adoption_init(&nopin, &OPS, NULL);
        nopin.adopted = true;
        CHECK(!adoption_allow_move(&nopin, true));
        fresh(&a);
        CHECK(adoption_offer(&a, mine, "Campo", NULL) == ADOPT_ADOPTED);
    }
    /* Unarmed: the pairing code needs the PIN, as before. */
    CHECK(adoption_offer_pairing(&a, other, "Outro") == ADOPT_NEED_PIN &&
          memcmp(a.key, mine, 32) == 0);
    /* Armed: the field's key is kept until another arrives; a card or the cable still ask for the
     * PIN. */
    CHECK(adoption_allow_move(&a, true) && a.move_armed);
    CHECK(memcmp(a.key, mine, 32) == 0 && sh.stores == 1);
    CHECK(adoption_offer(&a, other, "Outro", NULL) == ADOPT_NEED_PIN);
    CHECK(adoption_offer(&a, other, "Outro", "1234") == ADOPT_BAD_PIN);
    CHECK(a.move_armed && memcmp(a.key, mine, 32) == 0);
    /* A game joined: refused, still armed, still the old field. */
    sh.busy = true;
    CHECK(adoption_offer_pairing(&a, other, "Outro") == ADOPT_BUSY && memcmp(a.key, mine, 32) == 0);
    sh.busy = false;
    /* The pairing code's key moves it, once. */
    CHECK(adoption_offer_pairing(&a, other, "Outro") == ADOPT_READOPTED);
    CHECK(memcmp(a.key, other, 32) == 0 && strcmp(a.name, "Outro") == 0 && sh.stores == 2);
    CHECK(!a.move_armed && !a.move_now);
    CHECK(adoption_offer_pairing(&a, third, "Terceiro") == ADOPT_NEED_PIN &&
          memcmp(a.key, other, 32) == 0);
    /* Disarmed again by the shell when the code goes. */
    CHECK(adoption_allow_move(&a, true) && a.move_armed);
    CHECK(adoption_allow_move(&a, false) && !a.move_armed);
    CHECK(adoption_offer_pairing(&a, third, "Terceiro") == ADOPT_NEED_PIN);
    /* A store that fails keeps the old field and the arming. */
    CHECK(adoption_allow_move(&a, true));
    sh.store_fails = true;
    CHECK(adoption_offer_pairing(&a, third, "Terceiro") == ADOPT_STORE_FAILED);
    CHECK(memcmp(a.key, other, 32) == 0 && a.move_armed);
    sh.store_fails = false;
    /* The PIN's wait refuses before anything: no arming in one, and an armed move stops in one. */
    for (int i = 0; i < ADOPTION_PIN_TRIES; i++) adoption_offer(&a, third, "", "0000");
    CHECK(adoption_offer_pairing(&a, third, "Terceiro") == ADOPT_LOCKED);
    CHECK(!adoption_allow_move(&a, true)); /* no arming during a wait */
    CHECK(adoption_offer_pairing(&a, third, "Terceiro") == ADOPT_LOCKED);
    CHECK(memcmp(a.key, other, 32) == 0);
}

void run_adoption_tests(void)
{
    test_move_armed();
    test_card_vectors();
    test_join_card_is_no_field_card();
    test_names();
    test_rules();
    test_tap_and_pin();
    test_commands();
}
