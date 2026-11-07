/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Secure boot digest revocation (main/sb_revoke.c) with the eFuses faked: the instruction's form,
 * its Ed25519 signature (a vector made by Python's cryptography, as tools/firmware_release.py
 * revoke-sb-digest signs, with RFC 8032 TEST 1's public test key: never a project key), and the
 * refusals: the running image's key, the last trusted digest, an unknown or revoked slot, a box
 * without secure boot, an eFuse that does not take the bit. The fake counts burns: a refusal
 * never burns.
 */
#include <string.h>

#include "check.h"
#include "firmware_vectors.h"
#include "monocypher-ed25519.h"
#include "sb_revoke.h"

/* SHA-256("atalaia test secure boot key: ci") and ("...: root"), signed with RFC 8032 TEST 1's
 * key (fw_signing_key's seed) by Python's cryptography. */
static const char CI_HEX[] = "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9";
static const char CI_SIG[] =
    "ImH55+uGCOigpTucIneiZnE9+H6Wv/+AtZpdWfho2IzwjTzjLfKnPaXAVPAB7cWPbgmAImliI8cqqmprAuWqBA==";
static const char ROOT_HEX[] = "804dec63138fd5bed1202a77f0d9741a5290e1167f4d5563de488616753cfaa6";
static const char ROOT_SIG[] =
    "FNY4QuzyWJuG8wiuTpL/LfTaWB9CUa3JbH06WrLrDyKz5Gva1PaFINV30Gz5PC4/PTUce+VtJC8vgJTqMsIgAw==";

typedef struct {
    sb_state_t state;
    bool readable;
    bool burn_works;  /* the burn reports success */
    bool burn_sticks; /* and the bit reads back */
    int burns;
    int last_slot;
} fake_t;

static bool fake_read(sb_state_t *out, void *ctx)
{
    fake_t *f = ctx;
    if (!f->readable) return false;
    *out = f->state;
    return true;
}

static bool fake_burn(int slot, void *ctx)
{
    fake_t *f = ctx;
    f->burns++;
    f->last_slot = slot;
    if (f->burn_sticks) f->state.revoked[slot] = true;
    return f->burn_works;
}

static void hex_to(const char *hex, uint8_t out[32])
{
    for (int i = 0; i < 32; i++) {
        unsigned v = 0;
        for (int k = 0; k < 2; k++) {
            char c = hex[2 * i + k];
            v = v * 16 + (unsigned)(c <= '9' ? c - '0' : c - 'a' + 10);
        }
        out[i] = (uint8_t)v;
    }
}

/* A burned box as planned: root in slot 0, CI in slot 1, slot 2 empty; running a root-signed
 * image (the release after a CI key leak). */
static fake_t burned_box(void)
{
    fake_t f;
    memset(&f, 0, sizeof(f));
    f.readable = f.burn_works = f.burn_sticks = true;
    f.last_slot = -1;
    f.state.secure_boot = true;
    f.state.present[0] = f.state.present[1] = true;
    hex_to(ROOT_HEX, f.state.digest[0]);
    hex_to(CI_HEX, f.state.digest[1]);
    f.state.running_count = 1;
    hex_to(ROOT_HEX, f.state.running[0]);
    return f;
}

static void line(char *out, const char *hex, const char *sig)
{
    strcpy(out, hex);
    strcat(out, " ");
    strcat(out, sig);
}

static const uint8_t (*root_keys(void))[32]
{
    static uint8_t k[1][32];
    memcpy(k[0], fw_signing_key, 32);
    return (const uint8_t(*)[32])k;
}

static sb_revoke_result_t run(fake_t *f, const char *text, int *slot)
{
    sb_revoke_ops_t ops = {.read_state = fake_read, .burn_revoke = fake_burn, .ctx = f};
    return sb_revoke_run(text, root_keys(), 1, &ops, slot);
}

static void test_message_and_parse(void)
{
    uint8_t d[32];
    hex_to(CI_HEX, d);
    char msg[SB_REVOKE_MESSAGE_LEN + 1];
    CHECK(sb_revoke_message(d, msg, sizeof(msg)) == SB_REVOKE_MESSAGE_LEN);
    CHECK(strcmp(msg, "atalaia-secure-boot-revoke-v1\nplatform=esp32s3\ndigest="
                      "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9\n") == 0);
    CHECK(sb_revoke_message(d, msg, SB_REVOKE_MESSAGE_LEN) == 0); /* no room for the NUL */

    char text[SB_REVOKE_TEXT_MAX];
    sb_revoke_instruction_t ins;
    line(text, CI_HEX, CI_SIG);
    CHECK(strlen(text) == 153);
    CHECK(sb_revoke_parse(text, &ins));
    CHECK(memcmp(ins.digest, d, 32) == 0);
    CHECK(sb_revoke_signed(&ins, root_keys(), 1));
    /* Upper-case hex is the same digest. */
    char upper[SB_REVOKE_TEXT_MAX];
    strcpy(upper, text);
    for (int i = 0; i < 64; i++) {
        if (upper[i] >= 'a' && upper[i] <= 'f') upper[i] = (char)(upper[i] - 32);
    }
    CHECK(sb_revoke_parse(upper, &ins) && sb_revoke_signed(&ins, root_keys(), 1));

    static const char *const bad[] = {
        "",
        "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9",
        /* two spaces */
        "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9  "
        "ImH55+uGCOigpTucIneiZnE9+"
        "H6Wv/+AtZpdWfho2IzwjTzjLfKnPaXAVPAB7cWPbgmAImliI8cqqmprAuWqBA==",
        /* a non-hex digit */
        "x9bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9 ImH55+uGCOigpTucIneiZnE9+"
        "H6Wv/+AtZpdWfho2IzwjTzjLfKnPaXAVPAB7cWPbgmAImliI8cqqmprAuWqBA==",
        /* the signature's padding missing */
        "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9 ImH55+uGCOigpTucIneiZnE9+"
        "H6Wv/+AtZpdWfho2IzwjTzjLfKnPaXAVPAB7cWPbgmAImliI8cqqmprAuWqBAAA",
        /* trailing text */
        "59bfba86f71e817ab31f06f1d8ba59e715abdd5a365742da0070683c42d26ee9 ImH55+uGCOigpTucIneiZnE9+"
        "H6Wv/+AtZpdWfho2IzwjTzjLfKnPaXAVPAB7cWPbgmAImliI8cqqmprAuWqBA== 1234",
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) CHECK(!sb_revoke_parse(bad[i], &ins));
    CHECK(!sb_revoke_parse(NULL, &ins));
}

static void test_signature(void)
{
    char text[SB_REVOKE_TEXT_MAX];
    fake_t f = burned_box();
    int slot = 7;

    /* The root's digest signature on the CI digest: refused before anything is read. */
    line(text, CI_HEX, ROOT_SIG);
    f.readable = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_BAD_SIGNATURE && slot == -1);
    /* Another key (RFC 8032 TEST 2's) does not sign it. */
    line(text, CI_HEX, CI_SIG);
    sb_revoke_ops_t ops = {.read_state = fake_read, .burn_revoke = fake_burn, .ctx = &f};
    CHECK(sb_revoke_run(text, (const uint8_t(*)[32])fw_other_key, 1, &ops, &slot) ==
          SB_REVOKE_BAD_SIGNATURE);
    /* No key at all. */
    CHECK(sb_revoke_run(text, NULL, 0, &ops, &slot) == SB_REVOKE_NO_KEY);
    /* A flipped bit in the signature. */
    text[65 + 10] = text[65 + 10] == 'A' ? 'B' : 'A';
    CHECK(run(&f, text, &slot) == SB_REVOKE_BAD_SIGNATURE);
    /* Garbage. */
    CHECK(run(&f, "revoke everything", &slot) == SB_REVOKE_BAD_FORM);
    CHECK(f.burns == 0);

    /* A signature made here with monocypher by the same test key verifies too (Ed25519 is
     * deterministic: it is the Python signature). */
    uint8_t seed[32], sk[64], pk[32];
    static const uint8_t t1_seed[32] = {0x9d, 0x61, 0xb1, 0x9d, 0xef, 0xfd, 0x5a, 0x60,
                                        0xba, 0x84, 0x4a, 0xf4, 0x92, 0xec, 0x2c, 0xc4,
                                        0x44, 0x49, 0xc5, 0x69, 0x7b, 0x32, 0x69, 0x19,
                                        0x70, 0x3b, 0xac, 0x03, 0x1c, 0xae, 0x7f, 0x60};
    memcpy(seed, t1_seed, 32);
    crypto_ed25519_key_pair(sk, pk, seed);
    CHECK(memcmp(pk, fw_signing_key, 32) == 0);
    sb_revoke_instruction_t ins;
    line(text, CI_HEX, CI_SIG);
    CHECK(sb_revoke_parse(text, &ins));
    char msg[SB_REVOKE_MESSAGE_LEN + 1];
    sb_revoke_message(ins.digest, msg, sizeof(msg));
    uint8_t sig[64];
    crypto_ed25519_sign(sig, sk, (const uint8_t *)msg, SB_REVOKE_MESSAGE_LEN);
    CHECK(memcmp(sig, ins.signature, 64) == 0);
}

static void test_revokes_the_ci_key(void)
{
    char text[SB_REVOKE_TEXT_MAX];
    fake_t f = burned_box();
    int slot = -1;
    line(text, CI_HEX, CI_SIG);
    CHECK(run(&f, text, &slot) == SB_REVOKE_DONE);
    CHECK(slot == 1 && f.burns == 1 && f.last_slot == 1 && f.state.revoked[1]);
    /* Again: already done, nothing burned. */
    CHECK(run(&f, text, &slot) == SB_REVOKE_ALREADY && slot == 1 && f.burns == 1);
    /* The NULL slot pointer is fine. */
    fake_t g = burned_box();
    CHECK(run(&g, text, NULL) == SB_REVOKE_DONE && g.burns == 1);
}

static void test_refusals(void)
{
    char text[SB_REVOKE_TEXT_MAX];
    int slot;

    /* The running image is signed with the CI key (a CI release): never revoke it. */
    fake_t f = burned_box();
    hex_to(CI_HEX, f.state.running[0]);
    line(text, CI_HEX, CI_SIG);
    CHECK(run(&f, text, &slot) == SB_REVOKE_RUNNING && slot == 1 && f.burns == 0);
    /* Signed with both, as the bootloader is: still the running image's key. */
    f.state.running_count = 2;
    hex_to(ROOT_HEX, f.state.running[1]);
    CHECK(run(&f, text, &slot) == SB_REVOKE_RUNNING && f.burns == 0);

    /* The root key while the CI key is revoked: the last trusted one. The running image here is
     * signed with neither, which a burned box never boots, but the last-key rule holds anyway. */
    f = burned_box();
    f.state.revoked[1] = true;
    memset(f.state.running[0], 0x5a, 32);
    line(text, ROOT_HEX, ROOT_SIG);
    CHECK(run(&f, text, &slot) == SB_REVOKE_LAST && slot == 0 && f.burns == 0);
    /* With a key in the spare slot the root can go. */
    f.state.present[2] = true;
    memset(f.state.digest[2], 0x33, 32);
    CHECK(run(&f, text, &slot) == SB_REVOKE_DONE && slot == 0 && f.burns == 1);

    /* A digest no slot holds. */
    f = burned_box();
    memset(f.state.digest[1], 0x44, 32);
    line(text, CI_HEX, CI_SIG);
    CHECK(run(&f, text, &slot) == SB_REVOKE_UNKNOWN_DIGEST && slot == -1 && f.burns == 0);
    /* The digest in a slot whose key block is absent does not count. */
    f = burned_box();
    f.state.present[1] = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_UNKNOWN_DIGEST && f.burns == 0);

    /* No secure boot: nothing to revoke. */
    f = burned_box();
    f.state.secure_boot = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_NOT_SECURE_BOOT && f.burns == 0);

    /* The running image's signature blocks unknown, or the eFuses unreadable: refused. */
    f = burned_box();
    f.state.running_count = 0;
    CHECK(run(&f, text, &slot) == SB_REVOKE_NO_STATE && f.burns == 0);
    f = burned_box();
    f.readable = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_NO_STATE && f.burns == 0);

    /* The eFuse refuses, or the bit does not read back. */
    f = burned_box();
    f.burn_works = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_EFUSE && f.burns == 1);
    f = burned_box();
    f.burn_sticks = false;
    CHECK(run(&f, text, &slot) == SB_REVOKE_EFUSE && f.burns == 1);
}

typedef struct {
    int calls;
    sb_revoke_result_t results[4];
} reports_t;

static void collect(int index, sb_revoke_result_t r, int slot, void *ctx)
{
    (void)slot;
    reports_t *rep = ctx;
    if (index < 4) rep->results[index] = r;
    rep->calls++;
}

static void test_builtin_list(void)
{
    char ci[SB_REVOKE_TEXT_MAX], root[SB_REVOKE_TEXT_MAX], list[3 * SB_REVOKE_TEXT_MAX];
    line(ci, CI_HEX, CI_SIG);
    line(root, ROOT_HEX, ROOT_SIG);
    fake_t f = burned_box();
    sb_revoke_ops_t ops = {.read_state = fake_read, .burn_revoke = fake_burn, .ctx = &f};
    reports_t rep;

    memset(&rep, 0, sizeof(rep));
    CHECK(sb_revoke_run_list("", root_keys(), 1, &ops, collect, &rep) == 0 && rep.calls == 0);
    CHECK(sb_revoke_run_list(NULL, root_keys(), 1, &ops, NULL, NULL) == 0);

    /* CI revoked; the root refused (the running image's key); the CI again: already. */
    strcpy(list, ci);
    strcat(list, ", ");
    strcat(list, root);
    strcat(list, ",");
    strcat(list, ci);
    strcat(list, " ");
    memset(&rep, 0, sizeof(rep));
    CHECK(sb_revoke_run_list(list, root_keys(), 1, &ops, collect, &rep) == 1);
    CHECK(rep.calls == 3);
    CHECK(rep.results[0] == SB_REVOKE_DONE && rep.results[1] == SB_REVOKE_RUNNING &&
          rep.results[2] == SB_REVOKE_ALREADY);
    CHECK(f.burns == 1 && f.state.revoked[1] && !f.state.revoked[0]);

    /* An overlong entry is a bad form, not an overflow. */
    char longer[2 * SB_REVOKE_TEXT_MAX];
    memset(longer, 'a', sizeof(longer) - 1);
    longer[sizeof(longer) - 1] = '\0';
    memset(&rep, 0, sizeof(rep));
    CHECK(sb_revoke_run_list(longer, root_keys(), 1, &ops, collect, &rep) == 1);
    CHECK(rep.results[0] == SB_REVOKE_BAD_FORM);
}

static void test_names(void)
{
    CHECK(strcmp(sb_revoke_result_name(SB_REVOKE_DONE), "done") == 0);
    CHECK(strcmp(sb_revoke_result_name(SB_REVOKE_RUNNING), "running_key") == 0);
    CHECK(strcmp(sb_revoke_result_name(SB_REVOKE_LAST), "last_key") == 0);
    CHECK(strcmp(sb_revoke_result_name(SB_REVOKE_EFUSE), "efuse") == 0);
    CHECK(strcmp(sb_revoke_result_name((sb_revoke_result_t)99), "unknown") == 0);
}

void run_sb_revoke_tests(void)
{
    test_message_and_parse();
    test_signature();
    test_revokes_the_ci_key();
    test_refusals();
    test_builtin_list();
    test_names();
}
