/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The field's logo on the Field Box (main/box_logo.c, decision PKG-1; protocol/mode-packages.md,
 * section 8) from a fake controller, into a real folder: the release text's parse, a first fetch
 * kept under the source image's id, an unchanged id that downloads nothing, a new id that replaces
 * it, a controller with no logo that removes it, and every failure (no Wi-Fi, dead addresses, a
 * wrong size, hash or header, a broken or cancelled download) that leaves what the box kept as it
 * was, with no half-written file.
 */
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "box_logo.h"
#include "check.h"

#define ID_A "1111111111111111111111111111111111111111111111111111111111111111"
#define ID_B "2222222222222222222222222222222222222222222222222222222222222222"

static struct {
    bool wifi;
    bool dead[2];
    bool offered; /* the release is 200 (404 otherwise) */
    char id[65];
    uint8_t bytes[BL_BYTES];
    bool bad_release; /* a text that is not a release */
    bool lie_sha;     /* the release's SHA-256 is not the bytes' */
    size_t short_by;  /* bytes not sent at the end */
    size_t extra;     /* bytes sent after the bytes */
    int64_t length;   /* Content-Length: -2: the real one */
    bool read_error;
    size_t cancel_at;
    int gets, opens, net_ups, net_downs;
    size_t pos, served;
} fake;

static char tmp[96];

static void to_hex(const uint8_t *d, char out[65])
{
    for (int i = 0; i < 32; i++) snprintf(out + 2 * i, 3, "%02x", d[i]);
}

/* A logo: header and a pattern that depends on seed. */
static void make_logo(uint8_t seed)
{
    memcpy(fake.bytes, "ALG1", 4);
    fake.bytes[4] = BL_SIDE;
    fake.bytes[5] = 0;
    fake.bytes[6] = BL_SIDE;
    fake.bytes[7] = 0;
    for (size_t i = BL_HEADER; i < BL_BYTES; i++) fake.bytes[i] = (uint8_t)(i * 7 + seed);
}

static bool f_net_up(void *ctx)
{
    (void)ctx;
    fake.net_ups++;
    return fake.wifi;
}

static void f_net_down(void *ctx)
{
    (void)ctx;
    fake.net_downs++;
}

static bool dead(const char *base)
{
    return (fake.dead[0] && strcmp(base, "https://a.example") == 0) ||
           (fake.dead[1] && strcmp(base, "https://b.example") == 0);
}

static int f_get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    fake.gets++;
    if (dead(base)) return -1;
    if (strcmp(path, BL_PATH "/release") != 0 || !fake.offered) return -2;
    if (fake.bad_release) return snprintf(buf, cap, "hello\n");
    uint8_t digest[32];
    atalaia_sha256(fake.bytes, BL_BYTES, digest);
    char hex[65];
    to_hex(digest, hex);
    if (fake.lie_sha) hex[0] = hex[0] == '0' ? '1' : '0';
    return snprintf(buf, cap, "atalaia-box-logo-v1\nid=%s\nsha256=%s\nbytes=%u\n", fake.id, hex,
                    (unsigned)BL_BYTES);
}

static bool f_open(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    fake.opens++;
    *length = -1;
    if (dead(base)) return false;
    if (strcmp(path, BL_PATH) != 0 || !fake.offered) {
        *length = -2;
        return false;
    }
    fake.pos = 0;
    fake.served = BL_BYTES + fake.extra - fake.short_by;
    *length = fake.length != -2 ? fake.length : (int64_t)fake.served;
    return true;
}

static int f_read(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    if (fake.read_error && fake.pos > 0) return -1;
    size_t n = fake.served - fake.pos < 1000 ? fake.served - fake.pos : 1000;
    if (n > cap) n = cap;
    for (size_t i = 0; i < n; i++) {
        size_t at = fake.pos + i;
        buf[i] = at < BL_BYTES ? fake.bytes[at] : 0x41;
    }
    fake.pos += n;
    return (int)n;
}

static void f_close(void *ctx)
{
    (void)ctx;
}

static bool f_cancelled(void *ctx)
{
    (void)ctx;
    return fake.cancel_at != 0 && fake.pos >= fake.cancel_at;
}

static const fw_io_t IO = {.net_up = f_net_up,
                           .net_down = f_net_down,
                           .get_text = f_get_text,
                           .open = f_open,
                           .read = f_read,
                           .close = f_close,
                           .cancelled = f_cancelled};

static atalaia_join_t join;
static uint8_t buf[4096];

static void fresh(void)
{
    static int n;
    box_logo_unload();
    memset(&fake, 0, sizeof(fake));
    fake.wifi = true;
    fake.offered = true;
    fake.length = -2;
    snprintf(fake.id, sizeof(fake.id), "%s", ID_A);
    make_logo(1);
    snprintf(tmp, sizeof(tmp), "/tmp/atalaia_logo_%d_%d", (int)getpid(), n++);
    mkdir(tmp, 0755);
    CHECK(box_logo_init(tmp) == 0);
    memset(&join, 0, sizeof(join));
    join.has_ca = true;
    join.url_count = 2;
    snprintf(join.urls[0], sizeof(join.urls[0]), "https://a.example");
    snprintf(join.urls[1], sizeof(join.urls[1]), "https://b.example");
}

static bl_result_t run(void)
{
    return box_logo_run(&join, &IO, buf, sizeof(buf));
}

static bool kept_is(const char *id)
{
    char got[BL_ID_LEN + 1];
    return box_logo_kept(got) && strcmp(got, id) == 0;
}

static bool no_leftovers(void)
{
    char p[160];
    snprintf(p, sizeof(p), "%s/logo.new", tmp);
    return access(p, F_OK) != 0;
}

static void test_parse(void)
{
    char id[65], sha[65];
    uint32_t n = 0;
    const char *good = "atalaia-box-logo-v1\nid=" ID_A "\nsha256=" ID_B "\nbytes=18440\n";
    CHECK(box_logo_parse_release(good, strlen(good), id, sha, &n));
    CHECK(strcmp(id, ID_A) == 0 && strcmp(sha, ID_B) == 0 && n == 18440);
    /* The shared vector's text (protocol/vectors/box_logo.json). */
    const char *vec =
        "atalaia-box-logo-v1\nid=abababababababababababababababababababababababababababababababab\n"
        "sha256=039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81\nbytes=3\n";
    CHECK(box_logo_parse_release(vec, strlen(vec), id, sha, &n) && n == 3);
    const char *bad[] = {
        "",
        "hello\n",
        "atalaia-box-logo-v2\nid=" ID_A "\nsha256=" ID_B "\nbytes=18440\n",
        "atalaia-box-logo-v1\nid=" ID_A "\nsha256=" ID_B "\nbytes=18440",
        "atalaia-box-logo-v1\nid=" ID_A "\nsha256=" ID_B "\nbytes=\n",
        "atalaia-box-logo-v1\nid=" ID_A "\nsha256=" ID_B "\nbytes=18x\n",
        "atalaia-box-logo-v1\nid=" ID_A "\nsha256=" ID_B "\nbytes=1\nmore\n",
        "atalaia-box-logo-v1\nid=ABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCDEFABCD\n"
        "sha256=" ID_B "\nbytes=18440\n",
        "atalaia-box-logo-v1\nid=" ID_A "\nsha256=22\nbytes=18440\n"};
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        CHECK(!box_logo_parse_release(bad[i], strlen(bad[i]), id, sha, &n));
    }
}

static void test_first_fetch_and_unchanged(void)
{
    fresh();
    CHECK(!box_logo_kept(NULL) && box_logo_load() == NULL);
    CHECK(run() == BL_KEPT);
    CHECK(kept_is(ID_A) && no_leftovers());
    CHECK(fake.opens == 1 && fake.net_ups == 1 && fake.net_downs == 1);
    const uint16_t *px = box_logo_load();
    CHECK(px != NULL);
    CHECK(px != NULL && memcmp(px, fake.bytes + BL_HEADER, BL_PIXELS * 2) == 0);
    box_logo_unload();
    /* The same id: asked, not downloaded. */
    CHECK(run() == BL_KEPT);
    CHECK(fake.opens == 1 && fake.gets == 2);
    /* The first address down: the second answers. */
    fake.dead[0] = true;
    CHECK(run() == BL_KEPT && fake.gets == 4);
}

static void test_replaced_and_removed(void)
{
    fresh();
    CHECK(run() == BL_KEPT);
    snprintf(fake.id, sizeof(fake.id), "%s", ID_B);
    make_logo(9);
    CHECK(run() == BL_KEPT && kept_is(ID_B) && fake.opens == 2);
    const uint16_t *px = box_logo_load();
    CHECK(px != NULL && memcmp(px, fake.bytes + BL_HEADER, BL_PIXELS * 2) == 0);
    box_logo_unload();
    /* A controller with no logo a box can draw (404): none is kept, the Atalaia logo returns. */
    fake.offered = false;
    CHECK(run() == BL_NONE);
    CHECK(!box_logo_kept(NULL) && box_logo_load() == NULL);
}

static void test_failures_keep_what_was_kept(void)
{
    fresh();
    CHECK(run() == BL_KEPT);
    snprintf(fake.id, sizeof(fake.id), "%s", ID_B);
    make_logo(5);

    fake.wifi = false;
    fake.gets = fake.net_downs = 0;
    CHECK(run() == BL_NO_WIFI && kept_is(ID_A) && fake.gets == 0 && fake.net_downs == 1);
    fake.wifi = true;
    fake.dead[0] = fake.dead[1] = true;
    CHECK(run() == BL_UNREACHABLE && kept_is(ID_A));
    fake.dead[0] = fake.dead[1] = false;

    fake.bad_release = true;
    CHECK(run() == BL_BAD && kept_is(ID_A));
    fake.bad_release = false;
    fake.lie_sha = true;
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.lie_sha = false;
    fake.short_by = 10;
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.short_by = 0;
    fake.extra = 5;
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.extra = 0;
    fake.length = 100; /* a Content-Length other than the size */
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.length = -2;
    fake.read_error = true;
    CHECK(run() == BL_UNREACHABLE && kept_is(ID_A) && no_leftovers());
    fake.read_error = false;
    fake.cancel_at = 3000; /* a game started */
    CHECK(run() == BL_CANCELLED && kept_is(ID_A) && no_leftovers());
    fake.cancel_at = 0;
    /* A header of another format (the bytes are the promised size and hash). */
    fake.bytes[0] = 'X';
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.bytes[0] = 'A';
    fake.bytes[4] = 64; /* another size */
    CHECK(run() == BL_BAD && kept_is(ID_A) && no_leftovers());
    fake.bytes[4] = BL_SIDE;
    CHECK(run() == BL_KEPT && kept_is(ID_B));
}

static void test_join_and_storage(void)
{
    fresh();
    join.has_ca = false;
    CHECK(run() == BL_UNREACHABLE && fake.net_ups == 0);
    join.has_ca = true;
    join.url_count = 0;
    CHECK(run() == BL_UNREACHABLE && fake.net_ups == 0);
    join.url_count = 2;
    CHECK(box_logo_run(&join, &IO, buf, 100) == BL_STORAGE);
    /* A kept file that is damaged is not a kept logo (truncated, or another header). */
    CHECK(run() == BL_KEPT);
    char p[160];
    snprintf(p, sizeof(p), "%s/logo.bin", tmp);
    FILE *cut = fopen(p, "wb");
    CHECK(cut != NULL);
    if (cut) {
        CHECK(fwrite(buf, 1, 5000, cut) == 5000);
        fclose(cut);
    }
    CHECK(!box_logo_kept(NULL) && box_logo_load() == NULL);
    CHECK(run() == BL_KEPT && kept_is(ID_A)); /* fetched again */
    box_logo_forget();
    CHECK(!box_logo_kept(NULL));
    /* A fetch a power loss cut short leaves logo.new: the next start removes it. */
    snprintf(p, sizeof(p), "%s/logo.new", tmp);
    FILE *f = fopen(p, "wb");
    CHECK(f != NULL);
    if (f) fclose(f);
    CHECK(box_logo_init(tmp) == 0 && no_leftovers());
    CHECK(strcmp(box_logo_result_name(BL_NONE), "none") == 0);
}

void run_box_logo_tests(void)
{
    test_parse();
    test_first_fetch_and_unchanged();
    test_replaced_and_removed();
    test_failures_keep_what_was_kept();
    test_join_and_storage();
}
