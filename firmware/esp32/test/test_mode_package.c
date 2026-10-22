/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Signed mode packages on the Field Box (main/mode_package.c) against the shared
 * vectors (protocol/vectors/mode_package.json, as the Python reader): the
 * canonical archive and its files, every archive a reader refuses (fed whole and
 * in pieces of every awkward size), the signed releases and the release texts a
 * reader refuses, and key ids.
 */
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "mode_package.h"
#include "mode_package_vectors.h"

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static void unhex(const char *hex, uint8_t *out, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        out[i] = (uint8_t)(hexval(hex[2 * i]) << 4 | hexval(hex[2 * i + 1]));
    }
}

/* An archive of the vectors, put back together (the caller frees it). */
static uint8_t *rebuild(const mpv_seg_t *segs, size_t count, uint32_t size)
{
    uint8_t *a = calloc(1, size + 1);
    for (size_t i = 0; i < count; i++) {
        if (segs[i].len > 0) unhex(segs[i].hex, a + segs[i].offset, segs[i].len);
    }
    return a;
}

/* ---- the files the reader hands over ------------------------------------------------- */

typedef struct {
    char names[8][MP_NAME_MAX + 1];
    char texts[8][512];
    size_t lens[8];
    int count;
    int ended;
    int stop_at; /* -1: never stop */
} files_t;

static bool f_begin(void *ctx, const char *name, uint32_t size)
{
    files_t *f = (files_t *)ctx;
    if (f->count == f->stop_at) return false;
    if (f->count >= 8 || size >= sizeof(f->texts[0])) return false;
    snprintf(f->names[f->count], sizeof(f->names[0]), "%s", name);
    f->lens[f->count] = 0;
    f->count++;
    return true;
}

static bool f_data(void *ctx, const uint8_t *data, size_t len)
{
    files_t *f = (files_t *)ctx;
    int i = f->count - 1;
    memcpy(f->texts[i] + f->lens[i], data, len);
    f->lens[i] += len;
    f->texts[i][f->lens[i]] = '\0';
    return true;
}

static bool f_end(void *ctx)
{
    ((files_t *)ctx)->ended++;
    return true;
}

static const char *result_code(mp_tar_result_t r)
{
    switch (r) {
    case MP_TAR_OK: return "ok";
    case MP_TAR_BAD_ARCHIVE: return "bad_archive";
    case MP_TAR_MISMATCH: return "mismatch";
    case MP_TAR_TOO_BIG: return "too_big";
    default: return "stopped";
    }
}

/* Fed in pieces of step bytes. */
static mp_tar_result_t feed_in_steps(const uint8_t *a, size_t len, const char *expect, size_t step,
                                     const mp_tar_ops_t *ops)
{
    mp_tar_t t;
    mp_tar_init(&t, expect, MP_BOX_PACKAGE_MAX, ops);
    for (size_t off = 0; off < len; off += step) {
        size_t n = len - off < step ? len - off : step;
        mp_tar_result_t r = mp_tar_feed(&t, a + off, n);
        if (r != MP_TAR_OK) return r;
    }
    return mp_tar_finish(&t);
}

static const size_t STEPS[] = {1, 3, 100, 511, 512, 513, 4096, 100000};

static void test_archive(void)
{
    uint8_t *a = rebuild(mpv_archive_segs, mpv_archive_segs_count, MPV_ARCHIVE_SIZE);
    uint8_t digest[32];
    char hex[65];
    atalaia_sha256(a, MPV_ARCHIVE_SIZE, digest);
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", digest[i]);
    CHECK(strcmp(hex, MPV_ARCHIVE_SHA256) == 0);

    for (size_t s = 0; s < sizeof(STEPS) / sizeof(STEPS[0]); s++) {
        files_t f;
        memset(&f, 0, sizeof(f));
        f.stop_at = -1;
        mp_tar_ops_t ops = {f_begin, f_data, f_end, &f};
        CHECK(feed_in_steps(a, MPV_ARCHIVE_SIZE, MPV_ARCHIVE_ID, STEPS[s], &ops) == MP_TAR_OK);
        /* Every file, in order, with its text. */
        CHECK(f.count == (int)MPV_ARCHIVE_FILE_COUNT && f.ended == f.count);
        for (size_t i = 0; i < MPV_ARCHIVE_FILE_COUNT && (int)i < f.count; i++) {
            CHECK(strcmp(f.names[i], mpv_archive_files[i].name) == 0);
            CHECK(strcmp(f.texts[i], mpv_archive_files[i].text) == 0);
        }
    }
    /* Any root, or the one expected; another id is a mismatch. */
    CHECK(mp_tar_check(a, MPV_ARCHIVE_SIZE, NULL, MP_BOX_PACKAGE_MAX, NULL) == MP_TAR_OK);
    CHECK(mp_tar_check(a, MPV_ARCHIVE_SIZE, "org.example.other", MP_BOX_PACKAGE_MAX, NULL) ==
          MP_TAR_MISMATCH);
    /* Over the limit. */
    CHECK(mp_tar_check(a, MPV_ARCHIVE_SIZE, NULL, MPV_ARCHIVE_SIZE - 1, NULL) == MP_TAR_TOO_BIG);
    /* Cut short anywhere: never whole. */
    for (size_t cut = 0; cut < MPV_ARCHIVE_SIZE; cut += 256) {
        CHECK(mp_tar_check(a, cut, NULL, MP_BOX_PACKAGE_MAX, NULL) != MP_TAR_OK);
    }
    /* A callback that says stop. */
    files_t f;
    memset(&f, 0, sizeof(f));
    f.stop_at = 1;
    mp_tar_ops_t ops = {f_begin, f_data, f_end, &f};
    CHECK(mp_tar_check(a, MPV_ARCHIVE_SIZE, NULL, MP_BOX_PACKAGE_MAX, &ops) == MP_TAR_STOPPED);
    /* Any single byte changed in a header or the padding: refused. */
    for (size_t i = 0; i < MPV_ARCHIVE_SIZE; i += 7) {
        a[i] ^= 0x01;
        mp_tar_result_t r =
            mp_tar_check(a, MPV_ARCHIVE_SIZE, MPV_ARCHIVE_ID, MP_BOX_PACKAGE_MAX, NULL);
        a[i] ^= 0x01;
        /* A changed byte inside a file's text may still be text: those are for the hash. */
        bool in_text = false;
        for (uint32_t off = 0, k = 0; k < MPV_ARCHIVE_FILE_COUNT; k++) {
            size_t len = strlen(mpv_archive_files[k].text);
            if (i >= off + 512 && i < off + 512 + len) in_text = true;
            off += 512 + (uint32_t)((len + 511) / 512 * 512);
        }
        if (!in_text && r == MP_TAR_OK) {
            fprintf(stderr, "FAIL archive with byte %zu changed was accepted\n", i);
            check_failures++;
        }
        check_count++;
    }
    free(a);

    uint8_t *t = rebuild(mpv_tampered_segs, mpv_tampered_segs_count, MPV_ARCHIVE_SIZE);
    atalaia_sha256(t, MPV_ARCHIVE_SIZE, digest);
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", digest[i]);
    CHECK(strcmp(hex, MPV_ARCHIVE_SHA256) != 0); /* the hash tells it apart */
    free(t);
}

static void test_bad_archives(void)
{
    CHECK(MPV_BAD_ARCHIVE_COUNT == 28);
    for (size_t i = 0; i < MPV_BAD_ARCHIVE_COUNT; i++) {
        const mpv_archive_t *v = &mpv_bad_archives[i];
        uint8_t *a = rebuild(v->segs, v->seg_count, v->size);
        int before = check_failures;
        CHECK(strcmp(result_code(mp_tar_check(a, v->size, NULL, MP_BOX_PACKAGE_MAX, NULL)),
                     v->code) == 0);
        for (size_t s = 0; s < sizeof(STEPS) / sizeof(STEPS[0]); s++) {
            files_t f;
            memset(&f, 0, sizeof(f));
            f.stop_at = -1;
            mp_tar_ops_t ops = {f_begin, f_data, f_end, &f};
            CHECK(strcmp(result_code(feed_in_steps(a, v->size, NULL, STEPS[s], &ops)), v->code) ==
                  0);
        }
        if (check_failures != before) fprintf(stderr, "  in bad archive %s\n", v->name);
        free(a);
    }
}

static void test_releases(void)
{
    uint8_t keys[2][32];
    unhex(MPV_SIGNING_KEY_HEX, keys[0], 32);
    unhex(MPV_OTHER_KEY_HEX, keys[1], 32);
    char id[17];
    mp_key_id(keys[0], id);
    CHECK(strcmp(id, MPV_SIGNING_KEY_ID) == 0);
    mp_key_id(keys[1], id);
    CHECK(strcmp(id, MPV_OTHER_KEY_ID) == 0);

    CHECK(MPV_RELEASE_COUNT >= 7);
    for (size_t i = 0; i < MPV_RELEASE_COUNT; i++) {
        const mpv_release_t *v = &mpv_releases[i];
        int before = check_failures;
        mp_release_t rel;
        CHECK(mp_release_parse(v->text, strlen(v->text), &rel));
        CHECK(strcmp(rel.id, v->id) == 0 && strcmp(rel.version, v->version) == 0);
        CHECK(strcmp(mp_kind_name(rel.kind), v->kind) == 0);
        CHECK(strcmp(mp_tier_name(rel.tier), v->tier) == 0);
        CHECK(rel.size == v->size && strcmp(rel.sha256_hex, v->sha256) == 0);
        CHECK(rel.manifest_len == v->manifest_len);
        CHECK((mp_release_signer(&rel, v->text, (const uint8_t(*)[32])keys, 1) == 0) == v->valid);
        /* Two keys: the signing key is found at its place; none: nobody signed it. */
        CHECK((mp_release_signer(&rel, v->text, (const uint8_t(*)[32])keys + 1, 1) >= 0) == false);
        CHECK(mp_release_signer(&rel, v->text, (const uint8_t(*)[32])keys, 0) < 0);
        /* A byte of the manifest changed: the signature no longer holds. */
        if (v->valid) {
            char copy[MP_RELEASE_TEXT_MAX + 1];
            snprintf(copy, sizeof(copy), "%s", v->text);
            copy[30] ^= 1;
            mp_release_t again;
            if (mp_release_parse(copy, strlen(copy), &again)) {
                CHECK(mp_release_signer(&again, copy, (const uint8_t(*)[32])keys, 1) < 0);
            }
        }
        if (check_failures != before) fprintf(stderr, "  in release %s\n", v->name);
    }
}

static void test_bad_texts(void)
{
    CHECK(MPV_BAD_TEXT_COUNT >= 12);
    for (size_t i = 0; i < MPV_BAD_TEXT_COUNT; i++) {
        mp_release_t rel;
        if (mp_release_parse(mpv_bad_texts[i], strlen(mpv_bad_texts[i]), &rel)) {
            fprintf(stderr, "FAIL release text %zu was accepted\n", i);
            check_failures++;
        }
        check_count++;
    }
    /* Not ASCII, a NUL, too long, an empty text, a size over the controller's limit. */
    const mpv_release_t *v = &mpv_releases[0];
    char copy[MP_RELEASE_TEXT_MAX * 2];
    mp_release_t rel;
    snprintf(copy, sizeof(copy), "%s", v->text);
    copy[40] = (char)0xC3;
    CHECK(!mp_release_parse(copy, strlen(copy), &rel));
    snprintf(copy, sizeof(copy), "%s", v->text);
    CHECK(!mp_release_parse(copy, strlen(copy) + 1, &rel)); /* with its NUL */
    CHECK(!mp_release_parse(copy, 0, &rel));
    CHECK(!mp_release_parse(NULL, 10, &rel));
    memset(copy, 'a', sizeof(copy) - 1);
    copy[sizeof(copy) - 1] = '\0';
    CHECK(!mp_release_parse(copy, strlen(copy), &rel));
    const char *big = "atalaia-mode-package-v1\nid=org.a.b\nversion=1.0.0\nkind=mode\n"
                      "min_tier=reduced\nsize=1000001\nsha256=";
    snprintf(
        copy, sizeof(copy), "%s%s\nsignature=%s\n", big,
        "0000000000000000000000000000000000000000000000000000000000000000",
        "u8Lu6YRCD8W+0rm4J62jVFk/7bNRsC1CrVXA+Ma9KiX5yA1pCPsgWa5jvYIXmzeJRTOXFb1q4ZZo9l71eYVBCQ==");
    CHECK(!mp_release_parse(copy, strlen(copy), &rel));
}

static void test_ids(void)
{
    const char *good[] = {"org.example.relay", "a.b", "org.club.my-mode", "x1.y_2.z-3",
                          "org.atalaia.kill_confirmed"};
    const char *bad[] = {"",
                         "org",
                         "Org.a",
                         "org..a",
                         ".org.a",
                         "org.a.",
                         "org.-a",
                         "org._a",
                         "org.a b",
                         "org/a.b",
                         "org.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"};
    for (size_t i = 0; i < sizeof(good) / sizeof(good[0]); i++) {
        CHECK(mp_id_valid(good[i], strlen(good[i])));
    }
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        if (mp_id_valid(bad[i], strlen(bad[i]))) {
            fprintf(stderr, "FAIL id %s was taken\n", bad[i]);
            check_failures++;
        }
        check_count++;
    }
    CHECK(strcmp(mp_kind_name(MP_KIND_SCENARIO), "scenario") == 0);
    CHECK(strcmp(mp_kind_name((mp_kind_t)9), "?") == 0);
    CHECK(strcmp(mp_tier_name((mp_tier_t)9), "?") == 0);
}

void run_mode_package_tests(void)
{
    test_archive();
    test_bad_archives();
    test_releases();
    test_bad_texts();
    test_ids();
}
