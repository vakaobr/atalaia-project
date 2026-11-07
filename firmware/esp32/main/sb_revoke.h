/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Revoking a secure boot v2 public-key digest on a hardened Field Box (RELEASE_HARDENING.md,
 * section 3, "A leaked CI RSA key"; decisions HPR-*). A burned box's ROM downloader is in secure
 * download mode, where espefuse.py does not work, so a leaked secure boot key can only be revoked
 * by code running on the box: this. Platform-free, so the host tests run exactly this code with
 * the eFuses faked (test/test_sb_revoke.c); sb_revoke_esp.c reads the eFuses and burns the
 * revoke bit. Compiled only into a build with secure boot v2 (CONFIG_ATALAIA_SB_REVOKE, which
 * depends on it): the plain, bench, Wokwi, modem and I/O pod builds do not have it.
 *
 * The instruction: one secure boot digest (the SHA-256 of an RSA-3072 public key's signature
 * block fields, what espsecure.py digest_sbv2_public_key prints and espefuse burns) and an
 * Ed25519 signature, by a key of CONFIG_ATALAIA_SB_REVOKE_KEYS (the project's root release key,
 * offline), over exactly
 *
 *     atalaia-secure-boot-revoke-v1\n
 *     platform=esp32s3\n
 *     digest=<64 lower-case hex digits>\n
 *
 * In text: "<digest hex> <signature base64, 88 characters>", which
 * tools/firmware_release.py revoke-sb-digest prints. The same instruction serves every box (a
 * revocation is the same on all of them and can be done only once), so it carries no box id; a
 * replay changes nothing.
 *
 * It is refused unless secure boot is on, the digest is in one of the box's three digest slots and
 * not revoked yet, the running image does not carry a signature block of that key (so the box
 * never revokes the key its own image was verified with: the next boot would fail), and at least
 * one other slot stays trusted.
 */
#ifndef ATALAIA_SB_REVOKE_H
#define ATALAIA_SB_REVOKE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SB_REVOKE_HEADER   "atalaia-secure-boot-revoke-v1"
#define SB_REVOKE_PLATFORM "esp32s3"
#define SB_DIGEST_SLOTS    3  /* the ESP32-S3's secure boot digest slots */
#define SB_DIGEST_LEN      32 /* SHA-256 */
#define SB_REVOKE_KEYS_MAX 4  /* keys a firmware takes revocations from (as FW_KEYS_MAX) */
/* The signed text: the header line (30), "platform=esp32s3\n" (17), "digest=<64 hex>\n" (72). */
#define SB_REVOKE_MESSAGE_LEN 119
#define SB_REVOKE_TEXT_MAX    160 /* "<64 hex> <88 base64>" is 153 characters */

typedef struct {
    uint8_t digest[SB_DIGEST_LEN];
    uint8_t signature[64];
} sb_revoke_instruction_t;

/* What the box's eFuses and its running image say (sb_revoke_esp.c reads it). */
typedef struct {
    bool secure_boot;              /* SECURE_BOOT_EN is burned */
    bool present[SB_DIGEST_SLOTS]; /* a key block has the purpose SECURE_BOOT_DIGESTn */
    bool revoked[SB_DIGEST_SLOTS]; /* SECURE_BOOT_KEY_REVOKEn is burned */
    uint8_t digest[SB_DIGEST_SLOTS][SB_DIGEST_LEN];
    size_t running_count; /* signature blocks in the running app's image */
    uint8_t running[SB_DIGEST_SLOTS][SB_DIGEST_LEN]; /* their public keys' digests */
} sb_state_t;

typedef enum {
    SB_REVOKE_DONE = 0,      /* the slot's revoke bit is burned (and read back) */
    SB_REVOKE_BAD_FORM,      /* not "<64 hex> <88 base64>" */
    SB_REVOKE_NO_KEY,        /* this firmware has no revocation key */
    SB_REVOKE_BAD_SIGNATURE, /* no revocation key of this firmware signed it */
    SB_REVOKE_NO_STATE, /* the eFuses or the running image's signature blocks could not be read */
    SB_REVOKE_NOT_SECURE_BOOT, /* secure boot is not on: there is nothing to revoke */
    SB_REVOKE_UNKNOWN_DIGEST,  /* no slot holds that digest */
    SB_REVOKE_ALREADY,         /* its slot is revoked already: nothing to do */
    SB_REVOKE_RUNNING,         /* the running image is signed with that key: refused */
    SB_REVOKE_LAST,            /* it is the last trusted digest: refused */
    SB_REVOKE_EFUSE,           /* burning or reading back the revoke bit failed */
} sb_revoke_result_t;

/* The result's code ("done", "running_key", ...). */
const char *sb_revoke_result_name(sb_revoke_result_t r);

/* The exact bytes the signature covers (SB_REVOKE_MESSAGE_LEN of them, no NUL counted); out must
 * hold SB_REVOKE_MESSAGE_LEN + 1. Returns the length. */
size_t sb_revoke_message(const uint8_t digest[SB_DIGEST_LEN], char *out, size_t cap);

/* "<64 hex digits> <88 base64 characters>" (lower- or upper-case hex, one space, nothing else). */
bool sb_revoke_parse(const char *text, sb_revoke_instruction_t *out);

/* True when one of keys signed the instruction's message with Ed25519. */
bool sb_revoke_signed(const sb_revoke_instruction_t *ins, const uint8_t (*keys)[32],
                      size_t key_count);

/* The checks on the box's state: SB_REVOKE_DONE (meaning "go ahead") with *slot set, or the
 * reason not to. Does not look at the signature. */
sb_revoke_result_t sb_revoke_decide(const sb_state_t *s, const uint8_t digest[SB_DIGEST_LEN],
                                    int *slot);

typedef struct {
    bool (*read_state)(sb_state_t *out, void *ctx);
    bool (*burn_revoke)(int slot, void *ctx); /* esp_efuse_set_digest_revoke(slot) on the box */
    void *ctx;
} sb_revoke_ops_t;

/* The whole path: parse, signature, state, checks, burn, read back. *slot (may be NULL) is the
 * slot concerned, or -1. Nothing is burned unless every check passed. */
sb_revoke_result_t sb_revoke_run(const char *text, const uint8_t (*keys)[32], size_t key_count,
                                 const sb_revoke_ops_t *ops, int *slot);

/* Several instructions separated by commas (CONFIG_ATALAIA_SB_REVOKE_BUILTIN): each is run in turn;
 * returns how many were refused for a reason other than SB_REVOKE_ALREADY, and calls report (may
 * be NULL) once per instruction. An empty text is none. */
int sb_revoke_run_list(const char *list, const uint8_t (*keys)[32], size_t key_count,
                       const sb_revoke_ops_t *ops,
                       void (*report)(int index, sb_revoke_result_t r, int slot, void *ctx),
                       void *report_ctx);

#endif /* ATALAIA_SB_REVOKE_H */
