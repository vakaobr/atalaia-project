/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Signed mode packages on the Field Box (protocol/mode-packages.md, phase 5 plan
 * phase 13b, decisions P5B-10, P5B-14, P5C-8 and P5E-*): the release text a box
 * fetches, its Ed25519 signature checked with the mode keys built into the
 * firmware, and a streaming reader of the package's archive that takes exactly
 * the canonical ustar form the Python reader takes
 * (controller/atalaia_controller/mode_package.py). Platform-free: the host tests
 * run it against protocol/vectors/mode_package.json (test/test_mode_package.c).
 *
 * The archive reader never holds the archive: it is fed the bytes in pieces of
 * any size (as they come off the flash), checks each 512-byte header by building
 * the canonical header of the name and size it read and comparing every byte
 * (which covers the magic, the checksum, the type, the mode, the owners, the
 * times and the prefix field at once), checks the files' order, their UTF-8 text,
 * the zero padding and the two zero blocks at the end with nothing after them,
 * and hands each file's bytes to the caller, which keeps only what it needs.
 */
#ifndef ATALAIA_MODE_PACKAGE_H
#define ATALAIA_MODE_PACKAGE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "fw_update.h"

#define MP_MANIFEST_HEADER  "atalaia-mode-package-v1"
#define MP_ID_MAX           63  /* bytes of a mode id */
#define MP_RELEASE_TEXT_MAX 512 /* bytes of a release text (about 300 in practice) */
#define MP_BLOCK            512
#define MP_NAME_MAX         100 /* bytes of "<id>/<file>" in a header */
#define MP_FILES_MAX        64
#define MP_PACKAGE_MAX      1000000u       /* the controller's limit (P5-6) */
#define MP_BOX_PACKAGE_MAX  (256u * 1024u) /* what a box takes (P5B-12) */

typedef enum {
    MP_KIND_MODE = 0,
    MP_KIND_MODIFIER,
    MP_KIND_ROLE,
    MP_KIND_SCENARIO, /* runs on the controller only: a box never takes one */
} mp_kind_t;

typedef enum {
    MP_TIER_REDUCED = 0,
    MP_TIER_FULL,
} mp_tier_t;

const char *mp_kind_name(mp_kind_t kind);
const char *mp_tier_name(mp_tier_t tier);

/* A mode id: [a-z0-9][a-z0-9_-]* parts joined by dots, at least two, 1-63 bytes. */
bool mp_id_valid(const char *s, size_t n);

/* ---- release texts and signatures --------------------------------------------------- */

typedef struct {
    char id[MP_ID_MAX + 1];
    char version[FW_VERSION_MAX + 1];
    mp_kind_t kind;
    mp_tier_t tier;
    uint32_t size;
    uint8_t sha256[32];
    char sha256_hex[65];
    uint8_t signature[64];
    size_t manifest_len; /* the signed bytes: the text's first seven lines */
} mp_release_t;

/* Parses a release text (the manifest's seven lines and "signature=<base64>\n", exactly, as
 * parse_release_text in the Python). false if it is not one. */
bool mp_release_parse(const char *text, size_t len, mp_release_t *out);

/* The index of the key (of keys) that signed the manifest (text's first manifest_len bytes) with
 * Ed25519, or -1 if none did. */
int mp_release_signer(const mp_release_t *rel, const char *text, const uint8_t (*keys)[32],
                      size_t key_count);

/* A key's id: the first 16 hex digits of the SHA-256 of its 32 bytes (as release keys'). */
void mp_key_id(const uint8_t key[32], char out[17]);

/* ---- the archive ------------------------------------------------------------------- */

typedef enum {
    MP_TAR_OK = 0,
    MP_TAR_BAD_ARCHIVE, /* not the canonical form, or a name or file the format does not allow */
    MP_TAR_MISMATCH,    /* canonical, but its root folder is not the expected id */
    MP_TAR_TOO_BIG,     /* longer than the limit */
    MP_TAR_STOPPED,     /* a callback said stop (the caller knows why) */
} mp_tar_result_t;

typedef struct {
    /* A file starts: its name under the root ("node.lua", "assets/screens/x.yaml") and its
     * size. Each callback may be NULL; returning false stops the reader (MP_TAR_STOPPED). */
    bool (*file_begin)(void *ctx, const char *name, uint32_t size);
    bool (*file_data)(void *ctx, const uint8_t *data, size_t len);
    /* The file's bytes are all there and are UTF-8 text without NUL. */
    bool (*file_end)(void *ctx);
    void *ctx;
} mp_tar_ops_t;

typedef struct {
    const mp_tar_ops_t *ops;
    char expect[MP_ID_MAX + 1]; /* the root it must have; "" for any */
    uint32_t limit;
    uint32_t total; /* bytes fed so far */
    uint8_t state;
    uint8_t block[MP_BLOCK];
    size_t have;        /* bytes of block */
    uint32_t remaining; /* data bytes of the current file still to come */
    uint32_t pad;       /* zero bytes after it still to come */
    char root[MP_ID_MAX + 1];
    char prev[MP_NAME_MAX + 1]; /* the last file's name: the next one sorts after it */
    int files;
    uint8_t utf8_need;        /* continuation bytes still due */
    uint8_t utf8_lo, utf8_hi; /* the next continuation byte's range */
    mp_tar_result_t result;   /* the first failure, kept */
} mp_tar_t;

/* expect: the root folder the archive must have (NULL: any mode id); limit: its largest size. */
void mp_tar_init(mp_tar_t *t, const char *expect, uint32_t limit, const mp_tar_ops_t *ops);

/* The next bytes of the archive. MP_TAR_OK while it is still a canonical archive so far. */
mp_tar_result_t mp_tar_feed(mp_tar_t *t, const uint8_t *data, size_t len);

/* The archive is over: MP_TAR_OK only if it was whole (its two zero blocks at the end). */
mp_tar_result_t mp_tar_finish(mp_tar_t *t);

/* A whole archive in memory (the tests). */
mp_tar_result_t mp_tar_check(const uint8_t *archive, size_t len, const char *expect, uint32_t limit,
                             const mp_tar_ops_t *ops);

#endif /* ATALAIA_MODE_PACKAGE_H */
