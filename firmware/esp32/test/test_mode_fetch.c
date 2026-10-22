/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box fetching the mode packages a game needs (main/mode_fetch.c) from
 * a fake controller, into a real folder (main/mode_store.c), against the
 * contract (protocol/mode-packages.md, "Fetching missing modes"): every case of
 * the shared vectors' box_checks and reports, then the join's conditions, the
 * transport's results, the download's failures, the release and the archive
 * with packages these tests pack and sign with RFC 8032's public test key, the
 * script, its screens and the composed game in the sandbox, room among the
 * kept packages, replacement at the commit only, a commit cut short by a power
 * loss, the check of every kept release at boot, and forgetting.
 */
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "mode_fetch.h"
#include "mode_package_vectors.h"
#include "mode_store.h"
#include "monocypher-ed25519.h"
#include "preset_store.h"

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

/* ---- packing and signing, as tools/mode_package.py ---------------------------------- */

#define ARCHIVE_CAP (300u * 1024u)

static void octal(uint8_t *f, size_t width, uint32_t v)
{
    for (size_t i = width - 1; i-- > 0;) {
        f[i] = (uint8_t)('0' + (v & 7u));
        v >>= 3;
    }
    f[width - 1] = 0;
}

typedef struct {
    const char *name;
    const char *text;
} file_t;

/* The canonical archive of files (sorted by the caller) under root; its length. */
static size_t pack(const char *root, const file_t *files, size_t count, uint8_t *out)
{
    size_t pos = 0;
    for (size_t i = 0; i < count; i++) {
        uint8_t *h = out + pos;
        memset(h, 0, 512);
        char path[128];
        snprintf(path, sizeof(path), "%s/%s", root, files[i].name);
        memcpy(h, path, strlen(path));
        size_t len = strlen(files[i].text);
        octal(h + 100, 8, 0644);
        octal(h + 108, 8, 0);
        octal(h + 116, 8, 0);
        octal(h + 124, 12, (uint32_t)len);
        octal(h + 136, 12, 0);
        memset(h + 148, ' ', 8);
        h[156] = '0';
        memcpy(h + 257,
               "ustar\0"
               "00",
               8);
        octal(h + 329, 8, 0);
        octal(h + 337, 8, 0);
        uint32_t sum = 0;
        for (size_t k = 0; k < 512; k++) sum += h[k];
        octal(h + 148, 7, sum);
        pos += 512;
        memcpy(out + pos, files[i].text, len);
        size_t padded = (len + 511) / 512 * 512;
        memset(out + pos + len, 0, padded - len);
        pos += padded;
    }
    memset(out + pos, 0, 1024);
    return pos + 1024;
}

static uint8_t secret[64], public_key[32];

static void keys_init(void)
{
    uint8_t seed[32];
    unhex(MPV_SIGNING_SEED_HEX, seed, 32);
    crypto_ed25519_key_pair(secret, public_key, seed);
    uint8_t want[32];
    unhex(MPV_SIGNING_KEY_HEX, want, 32);
    CHECK(memcmp(want, public_key, 32) == 0);
}

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/* The release text of an archive, signed with the test key (or with size_override for a lie). */
static void sign(char *text, size_t cap, const char *id, const char *version, const char *kind,
                 const char *tier, const uint8_t *archive, size_t len, uint32_t size_override)
{
    uint8_t digest[32];
    atalaia_sha256(archive, len, digest);
    char hex[65];
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", digest[i]);
    int n = snprintf(text, cap,
                     "atalaia-mode-package-v1\nid=%s\nversion=%s\nkind=%s\nmin_tier=%s\nsize=%lu\n"
                     "sha256=%s\n",
                     id, version, kind, tier,
                     (unsigned long)(size_override ? size_override : (uint32_t)len), hex);
    uint8_t sig[64];
    crypto_ed25519_sign(sig, secret, (const uint8_t *)text, (size_t)n);
    char *p = text + n;
    p += sprintf(p, "signature=");
    for (int i = 0; i < 66; i += 3) {
        uint32_t v = (uint32_t)sig[i] << 16 | (uint32_t)(i + 1 < 64 ? sig[i + 1] : 0) << 8 |
                     (uint32_t)(i + 2 < 64 ? sig[i + 2] : 0);
        *p++ = B64[v >> 18 & 63];
        *p++ = B64[v >> 12 & 63];
        *p++ = i + 1 < 64 ? B64[v >> 6 & 63] : '=';
        *p++ = i + 2 < 64 ? B64[v & 63] : '=';
    }
    *p++ = '\n';
    *p = '\0';
}

/* ---- the fake controller --------------------------------------------------------------- */

typedef struct {
    char id[MP_ID_MAX + 1];
    char release[MP_RELEASE_TEXT_MAX + 64];
    uint8_t *archive;
    size_t len;
    bool no_package; /* the release, but 404 for the package */
} pkg_t;

typedef struct {
    bool wifi;
    bool url_dead[3];
    pkg_t pkgs[12];
    int count;
    int64_t length_override; /* -2: the real length */
    size_t serve_extra;      /* bytes sent after the archive */
    size_t serve_short;      /* bytes not sent at its end */
    bool read_error;
    uint32_t cancel_at; /* cancelled once this many bytes are read (0: never) */
    bool post_ok;
    /* What happened. */
    int net_ups, gets, opens, posts;
    char body[MF_REPORT_MAX], mac[65], post_base[80];
    const pkg_t *cur;
    size_t pos, served;
} fake_t;

static fake_t fake;

/* The controller holds nothing again. */
static void server_reset(void)
{
    for (int i = 0; i < fake.count; i++) free(fake.pkgs[i].archive);
    fake.count = 0;
}

static pkg_t *pkg_add(const char *id)
{
    pkg_t *p = &fake.pkgs[fake.count++];
    memset(p, 0, sizeof(*p));
    snprintf(p->id, sizeof(p->id), "%s", id);
    p->archive = calloc(1, ARCHIVE_CAP);
    return p;
}

static const pkg_t *pkg_of(const char *path, const char *what)
{
    const char *prefix = "/api/v1/mode-packages/";
    if (strncmp(path, prefix, strlen(prefix)) != 0) return NULL;
    const char *id = path + strlen(prefix);
    const char *slash = strchr(id, '/');
    if (slash == NULL || strcmp(slash + 1, what) != 0) return NULL;
    for (int i = 0; i < fake.count; i++) {
        if (strlen(fake.pkgs[i].id) == (size_t)(slash - id) &&
            strncmp(fake.pkgs[i].id, id, (size_t)(slash - id)) == 0) {
            return &fake.pkgs[i];
        }
    }
    return NULL;
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
}
static bool dead(const char *base)
{
    return (fake.url_dead[0] && strcmp(base, "https://a.example") == 0) ||
           (fake.url_dead[1] && strcmp(base, "https://b.example") == 0);
}
/* As fw_update_esp.c's: -1 no answer, -2 not 200 (404: not offered), -3 too long. */
static int f_get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    fake.gets++;
    if (dead(base)) return -1;
    const pkg_t *p = pkg_of(path, "release");
    if (p == NULL) return -2;
    if (strlen(p->release) >= cap) return -3;
    snprintf(buf, cap, "%s", p->release);
    return (int)strlen(p->release);
}
static bool f_open(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    fake.opens++;
    *length = -1;
    if (dead(base)) return false;
    fake.cur = pkg_of(path, "package");
    if (fake.cur == NULL || fake.cur->no_package) {
        fake.cur = NULL;
        *length = -2;
        return false;
    }
    fake.pos = 0;
    fake.served = fake.cur->len + fake.serve_extra - fake.serve_short;
    *length = fake.length_override != -2 ? fake.length_override : (int64_t)fake.served;
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
        buf[i] = at < fake.cur->len ? fake.cur->archive[at] : 0x41;
    }
    fake.pos += n;
    return (int)n;
}
static void f_close(void *ctx)
{
    (void)ctx;
    fake.cur = NULL;
}
static bool f_post(void *ctx, const char *base, const char *path, const char *body,
                   const char *mac_hex)
{
    (void)ctx;
    CHECK(strcmp(path, MF_REPORT_PATH) == 0);
    fake.posts++;
    snprintf(fake.post_base, sizeof(fake.post_base), "%s", base);
    snprintf(fake.body, sizeof(fake.body), "%s", body);
    snprintf(fake.mac, sizeof(fake.mac), "%s", mac_hex);
    return fake.post_ok;
}
static bool f_cancelled(void *ctx)
{
    (void)ctx;
    return fake.cancel_at != 0 && fake.pos >= fake.cancel_at;
}

static const fw_io_t IO = {
    .net_up = f_net_up,
    .net_down = f_net_down,
    .get_text = f_get_text,
    .open = f_open,
    .read = f_read,
    .close = f_close,
    .post = f_post,
    .cancelled = f_cancelled,
    .progress = NULL,
    .ctx = NULL,
};

/* ---- the box ------------------------------------------------------------------------- */

static char base[96];
static atalaia_join_t join;
static uint8_t keys[2][32];
static mf_job_t job;
static uint8_t buf[4096];
static char scratch[PRESET_SOURCE_MAX];
static const char *builtins[2];

static bool is_builtin(const char *id)
{
    for (size_t i = 0; i < 2; i++) {
        if (builtins[i] != NULL && strcmp(builtins[i], id) == 0) return true;
    }
    return false;
}

/* A new box: an empty storage folder, the fake controller with nothing on it. */
static void box(const char *mode_id)
{
    static int n;
    server_reset();
    memset(&fake, 0, sizeof(fake));
    fake.wifi = true;
    fake.post_ok = true;
    fake.length_override = -2;
    snprintf(base, sizeof(base), "/tmp/atalaia_mf_%d_%d", (int)getpid(), n++);
    mkdir(base, 0755);
    CHECK(preset_store_init(base) == 0);
    CHECK(mode_store_init(base) == 0);
    memset(&join, 0, sizeof(join));
    join.game_id = 77;
    join.node_id = 5;
    for (int i = 0; i < 16; i++) join.game_key[i] = (uint8_t)(i * 7 + 1);
    snprintf(join.teams[0], sizeof(join.teams[0]), "red");
    snprintf(join.teams[1], sizeof(join.teams[1]), "blue");
    join.team_count = 2;
    snprintf(join.mode_id, sizeof(join.mode_id), "%s", mode_id);
    snprintf(join.role, sizeof(join.role), "box");
    join.has_ca = true;
    join.url_count = 2;
    join.fetch_modes = true;
    snprintf(join.urls[0], sizeof(join.urls[0]), "https://a.example");
    snprintf(join.urls[1], sizeof(join.urls[1]), "https://b.example");
    memset(&job, 0, sizeof(job));
    memcpy(keys[0], public_key, 32);
    job.keys = (const uint8_t(*)[32])keys;
    job.key_count = 1;
    job.reduced = false;
    job.mem_limit = 256u * 1024u;
    builtins[0] = builtins[1] = NULL;
    job.builtin = is_builtin;
    job.join = &join;
    job.buf = buf;
    job.buf_cap = sizeof(buf);
    job.scratch = scratch;
    job.scratch_cap = sizeof(scratch);
}

static const char *const SCRIPT = "on(\"team_input.press\", function(e)\n"
                                  "  emit(\"x.example.relay\", { team = e.team })\nend)\n";
static const char *const SCREEN = "template: relay\nlayout:\n  - type: label\n    text: \"R\"\n";

/* A package served by the fake controller: script NULL: no node.lua. */
static pkg_t *serve(const char *id, const char *version, const char *kind, const char *tier,
                    const char *script)
{
    pkg_t *p = pkg_add(id);
    char yaml[256];
    snprintf(yaml, sizeof(yaml), "id: %s\nversion: %s\nkind: %s\nmin_tier: %s\nlicense: MIT\n", id,
             version, kind, tier);
    file_t files[3] = {
        {"assets/screens/relay.yaml", SCREEN}, {"mode.yaml", yaml}, {"node.lua", script}};
    p->len = pack(id, files, script ? 3 : 2, p->archive);
    sign(p->release, sizeof(p->release), id, version, kind, tier, p->archive, p->len, 0);
    return p;
}

static pkg_t *serve_files(const char *id, const file_t *files, size_t count)
{
    pkg_t *p = pkg_add(id);
    p->len = pack(id, files, count, p->archive);
    sign(p->release, sizeof(p->release), id, "1.0.0", "mode", "reduced", p->archive, p->len, 0);
    return p;
}

static bool file_is(const char *path, const char *text)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) return false;
    static char got[PRESET_SOURCE_MAX + 128];
    size_t n = fread(got, 1, sizeof(got) - 1, f);
    fclose(f);
    got[n] = '\0';
    return strcmp(got, text) == 0;
}

/* The last report: the part, the version read ("-" none), the result and the packages kept
 * now (kept: "-" or "id@version,..."), with the game key's HMAC of the body. */
static bool reported(const char *part, const char *version, const char *result, const char *kept)
{
    char want[MF_REPORT_MAX];
    snprintf(want, sizeof(want),
             "atalaia-mode-report-v1\ngame=77\nnode=5\nmode=%s\nversion=%s\nresult=%s\nkept=%s\n",
             part, version, result, kept);
    if (strcmp(fake.body, want) != 0) {
        fprintf(stderr, "  report was:\n%s  wanted:\n%s", fake.body, want);
        return false;
    }
    uint8_t mac[32];
    atalaia_hmac_sha256(join.game_key, 16, (const uint8_t *)want, strlen(want), mac);
    char hex[65];
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", mac[i]);
    return strcmp(hex, fake.mac) == 0;
}

static void put_segs(uint8_t *out, const mpv_seg_t *segs, size_t count)
{
    for (size_t s = 0; s < count; s++) {
        if (segs[s].len) unhex(segs[s].hex, out + segs[s].offset, segs[s].len);
    }
}

/* ---- the shared vectors: box_checks, box_limits, reports --------------------------------- */

static void test_box_check_vectors(void)
{
    CHECK(MPV_BOX_MAX_PACKAGE_BYTES == MP_BOX_PACKAGE_MAX);
    CHECK(MPV_BOX_MAX_FETCHED == MS_FETCHED_MAX && MPV_BOX_MAX_FETCHED_BYTES == MS_FETCHED_BYTES);
    CHECK(MPV_BOX_CHECK_COUNT >= 18);
    for (size_t i = 0; i < MPV_BOX_CHECK_COUNT; i++) {
        const mpv_box_check_t *v = &mpv_box_checks[i];
        box(v->wanted_id);
        int before = check_failures;
        pkg_t *p = pkg_add(v->wanted_id);
        snprintf(p->release, sizeof(p->release), "%s", v->release_text);
        switch (v->archive) {
        case MPV_ARCHIVE:
        case MPV_TRUNCATED:
            put_segs(p->archive, mpv_archive_segs, mpv_archive_segs_count);
            p->len = MPV_ARCHIVE_SIZE - (v->archive == MPV_TRUNCATED ? 512u : 0u);
            break;
        case MPV_TAMPERED:
            put_segs(p->archive, mpv_tampered_segs, mpv_tampered_segs_count);
            p->len = MPV_ARCHIVE_SIZE;
            break;
        case MPV_HEX:
            put_segs(p->archive, v->segs, v->seg_count);
            p->len = v->hex_size;
            break;
        default: p->no_package = true; break; /* refused before any download */
        }
        /* The archive as the box received it (box_check_archive): no Content-Length, the
         * connection closed after it. */
        fake.length_override = -1;
        for (size_t k = 0; k < v->key_count; k++) unhex(v->keys[k], keys[k], 32);
        job.key_count = v->key_count;
        job.reduced = v->reduced;
        job.mem_limit = v->reduced ? 64u * 1024u : 256u * 1024u;
        builtins[0] = v->builtin[0];
        builtins[1] = v->builtin[1];
        mf_result_t r = mf_run(&job, &IO);
        const char *want = strcmp(v->result, "ok") == 0 ? "installed" : v->result;
        CHECK(strcmp(mf_result_name(r), want) == 0);
        if (v->archive == MPV_NONE) CHECK(fake.opens == 0); /* refused before the download */
        if (r == MF_INSTALLED) {
            ms_fetched_t m;
            CHECK(mode_store_fetched(v->wanted_id, &m) && strcmp(m.key_id, v->key_id) == 0);
            CHECK(m.bytes == MPV_ARCHIVE_SIZE);
            char path[256];
            for (size_t k = 0; k < 4 && v->kept[k] != NULL; k++) {
                snprintf(path, sizeof(path), "%s/modes/%s/%s", base, v->wanted_id, v->kept[k]);
                CHECK(access(path, F_OK) == 0);
            }
            snprintf(path, sizeof(path), "%s/modes/%s/mode.yaml", base, v->wanted_id);
            CHECK(access(path, F_OK) != 0); /* never kept, never read */
            snprintf(path, sizeof(path), "%s/modes/%s/release", base, v->wanted_id);
            CHECK(file_is(path, v->release_text));
            CHECK(preset_store_find_mode(v->wanted_id) > 0);
            const builtin_screen_t *s =
                mode_store_screen(v->wanted_id, strlen(v->wanted_id), "relay");
            CHECK(s != NULL && strstr(s->yaml, "template: relay") != NULL);
            CHECK(job.installed == 1 && job.reported);
        } else {
            CHECK(!mode_store_has(v->wanted_id) && preset_store_find_mode(v->wanted_id) < 0);
            char stage[160];
            snprintf(stage, sizeof(stage), "%s/modes/.new", base);
            CHECK(access(stage, F_OK) != 0); /* nothing left on its way */
            CHECK(strcmp(job.part, v->wanted_id) == 0);
            /* no_key is refused before any network: nobody hears it over HTTPS. */
            CHECK((r == MF_NO_KEY) == (fake.posts == 0));
            if (fake.posts > 0) CHECK(strstr(fake.body, want) != NULL);
        }
        if (check_failures != before) {
            fprintf(stderr, "  in box check %s (the box said %s)\n", v->name, mf_result_name(r));
        }
    }
}

/* A fetched package's slot and script, as mode_store_commit leaves it. */
static void keep_bytes(const char *id, const char *version, uint32_t bytes)
{
    CHECK(mode_store_stage_begin());
    FILE *f = mode_store_stage_open("node.lua", "wb");
    CHECK(f != NULL);
    if (f) {
        fputs(SCRIPT, f);
        fclose(f);
    }
    ms_fetched_t m;
    memset(&m, 0, sizeof(m));
    snprintf(m.id, sizeof(m.id), "%s", id);
    snprintf(m.version, sizeof(m.version), "%s", version);
    snprintf(m.key_id, sizeof(m.key_id), "%s", MPV_SIGNING_KEY_ID);
    snprintf(m.sha256, sizeof(m.sha256), "%s", MPV_ARCHIVE_SHA256);
    m.bytes = bytes;
    CHECK(mode_store_commit(&m, "x\n", 2));
}

static void keep(const char *id, const char *version)
{
    keep_bytes(id, version, 1000);
}

static void test_report_vectors(void)
{
    CHECK(MPV_REPORT_COUNT >= 3);
    for (size_t i = 0; i < MPV_REPORT_COUNT; i++) {
        const mpv_report_t *v = &mpv_reports[i];
        box("org.club.none");
        for (size_t k = 0; k < 8 && v->kept_ids[k] != NULL; k++) {
            keep(v->kept_ids[k], v->kept_versions[k]);
        }
        join.game_id = v->game;
        join.node_id = v->node;
        unhex(MPV_REPORT_GAME_KEY_HEX, join.game_key, 16);
        mf_result_t r = MF_INSTALLED;
        while (strcmp(mf_result_name(r), v->result) != 0 && r <= MF_CANCELLED) {
            r = (mf_result_t)(r + 1);
        }
        CHECK(r <= MF_CANCELLED);
        char body[MF_REPORT_MAX], mac[65];
        size_t n = mf_report(&join, v->mode, r, v->version, body, sizeof(body), mac);
        CHECK(n == strlen(v->body) && strcmp(body, v->body) == 0);
        CHECK(strcmp(mac, v->mac) == 0);
        if (n != strlen(v->body) || strcmp(body, v->body) != 0) {
            fprintf(stderr, "  report %zu was:\n%s", i, body);
        }
    }
    /* Every result has its code, in the contract's order. */
    static const char *const names[] = {
        "installed",   "no_wifi",       "unreachable", "not_offered", "download", "no_key",
        "bad_release", "bad_signature", "kind",        "tier",        "builtin",  "too_big",
        "bad_hash",    "bad_archive",   "load",        "no_space",    "storage",  "cancelled"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        CHECK(strcmp(mf_result_name((mf_result_t)i), names[i]) == 0);
    }
    CHECK(strcmp(mf_result_name((mf_result_t)99), "?") == 0);
    /* Too small a buffer: nothing. */
    char small[40], mac[65];
    CHECK(mf_report(&join, "org.a.b", MF_INSTALLED, "1.0.0", small, sizeof(small), mac) == 0);
    char path[96];
    mf_path(path, sizeof(path), "org.a.b", "release");
    CHECK(strcmp(path, "/api/v1/mode-packages/org.a.b/release") == 0);
}

/* ---- the join and the network ----------------------------------------------------------- */

static void test_join_and_network(void)
{
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    /* Section 1: key 16, keys 13 and 14, a mode key, a missing part. */
    CHECK(mf_join_can_fetch(&join, 1));
    CHECK(!mf_join_can_fetch(&join, 0));
    join.fetch_modes = false;
    CHECK(!mf_join_can_fetch(&join, 1));
    join.fetch_modes = true;
    join.has_ca = false;
    CHECK(!mf_join_can_fetch(&join, 1));
    join.has_ca = true;
    join.url_count = 0;
    CHECK(!mf_join_can_fetch(&join, 1));
    join.url_count = 2;
    /* No key: refused before any network. */
    job.key_count = 0;
    CHECK(mf_run(&job, &IO) == MF_NO_KEY && fake.net_ups == 0 && fake.posts == 0);
    CHECK(strcmp(job.part, "org.club.relay") == 0);
    job.key_count = 1;
    /* No Wi-Fi: nobody to report to (the box says it over LoRa). */
    fake.wifi = false;
    CHECK(mf_run(&job, &IO) == MF_NO_WIFI && fake.net_ups == 1 && !job.reported);
    CHECK(fake.posts == 0 && strcmp(job.part, "org.club.relay") == 0);
    fake.wifi = true;
    /* Every address dead. */
    fake.url_dead[0] = fake.url_dead[1] = true;
    CHECK(mf_run(&job, &IO) == MF_UNREACHABLE && !job.reported && fake.posts == 0);
    /* The second address answers: it is the one used, and reported to. */
    fake.url_dead[0] = true;
    fake.url_dead[1] = false;
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    CHECK(strcmp(job.base, "https://b.example") == 0 && strcmp(fake.post_base, job.base) == 0);
    CHECK(reported("org.club.relay", "1.0.0", "installed", "org.club.relay@1.0.0"));
    /* Now nothing is missing: no network at all. */
    int ups = fake.net_ups;
    CHECK(mf_missing(&join) == 0 && !mf_join_can_fetch(&join, 1));
    CHECK(mf_run(&job, &IO) == MF_INSTALLED && fake.net_ups == ups);
    /* A mode id that is not one: nothing to ask for. */
    snprintf(join.mode_id, sizeof(join.mode_id), "Not An Id");
    CHECK(mf_missing(&join) < 0 && mf_run(&job, &IO) == MF_BAD_RELEASE);
    /* The controller does not offer it (404, or 409 once a game started). */
    box("org.club.relay");
    CHECK(mf_run(&job, &IO) == MF_NOT_OFFERED && job.reported);
    CHECK(reported("org.club.relay", "-", "not_offered", "-"));
    box("org.club.relay");
    pkg_t *p = serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    p->no_package = true;
    CHECK(mf_run(&job, &IO) == MF_NOT_OFFERED);
    CHECK(reported("org.club.relay", "1.0.0", "not_offered", "-"));
    /* A release text longer than a box reads. */
    box("org.club.relay");
    p = serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    memset(p->release, 'a', MP_RELEASE_TEXT_MAX + 10);
    p->release[MP_RELEASE_TEXT_MAX + 10] = '\0';
    CHECK(mf_run(&job, &IO) == MF_BAD_RELEASE);
    /* A report the controller does not take: not reported (LoRa). */
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    fake.post_ok = false;
    CHECK(mf_run(&job, &IO) == MF_INSTALLED && !job.reported && fake.posts == 1);
    /* Two parts missing: each fetched in order, each reported; the first failure stops. */
    box("org.club.main+org.club.mod+org.club.third");
    serve("org.club.main", "1.0.0", "mode", "reduced", SCRIPT);
    serve("org.club.mod", "2.0.0", "modifier", "reduced", "-- a modifier\n");
    mf_result_t r3 = mf_run(&job, &IO);
    CHECK(r3 == MF_NOT_OFFERED && fake.posts == 3 && job.installed == 2);
    CHECK(strcmp(job.part, "org.club.third") == 0);
    CHECK(reported("org.club.third", "-", "not_offered", "org.club.main@1.0.0,org.club.mod@2.0.0"));
    CHECK(mode_store_has("org.club.main") && mode_store_has("org.club.mod"));
}

/* ---- the download ----------------------------------------------------------------------- */

static void test_download(void)
{
    struct {
        const char *what;
        int64_t length;
        size_t extra, cut;
        bool read_error;
        uint32_t cancel_at;
        mf_result_t want;
    } cases[] = {
        {"a Content-Length that is not the size", 100, 0, 0, false, 0, MF_DOWNLOAD},
        {"more than the size", -1, 512, 0, false, 0, MF_DOWNLOAD},
        {"less than announced", -2, 0, 512, false, 0, MF_DOWNLOAD},
        {"less, nothing announced", -1, 0, 512, false, 0, MF_BAD_HASH},
        {"a read error", -2, 0, 0, true, 0, MF_DOWNLOAD},
        {"a game starts", -2, 0, 0, false, 1000, MF_CANCELLED},
        {"no Content-Length, whole", -1, 0, 0, false, 0, MF_INSTALLED},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        box("org.club.relay");
        pkg_t *p = serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
        if (cases[i].length == -2 && cases[i].cut) {
            fake.length_override = (int64_t)p->len; /* announced whole, then cut */
        } else {
            fake.length_override = cases[i].length;
        }
        fake.serve_extra = cases[i].extra;
        fake.serve_short = cases[i].cut;
        fake.read_error = cases[i].read_error;
        fake.cancel_at = cases[i].cancel_at;
        mf_result_t r = mf_run(&job, &IO);
        if (r != cases[i].want) {
            fprintf(stderr, "FAIL download, %s: %s\n", cases[i].what, mf_result_name(r));
            check_failures++;
        }
        check_count++;
        CHECK((r == MF_INSTALLED) == mode_store_has("org.club.relay"));
    }
    box("org.club.relay");
    pkg_t *p = serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    p->archive[600] ^= 1;
    CHECK(mf_run(&job, &IO) == MF_BAD_HASH && !mode_store_has("org.club.relay"));
    CHECK(reported("org.club.relay", "1.0.0", "bad_hash", "-"));
}

/* ---- the release (section 3's order) and the archive ------------------------------------ */

static void test_release_and_archive(void)
{
    /* The controller answers with another mode's release. */
    box("org.club.relay");
    pkg_t *p = serve("org.club.other", "1.0.0", "role", "reduced", SCRIPT);
    snprintf(p->id, sizeof(p->id), "org.club.relay");
    CHECK(mf_run(&job, &IO) == MF_BAD_RELEASE && fake.opens == 0);
    CHECK(reported("org.club.relay", "-", "bad_release", "-"));
    /* Signed by a key this firmware does not have; two keys (a mode key, a release key). */
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", SCRIPT);
    unhex(MPV_OTHER_KEY_HEX, keys[0], 32);
    CHECK(mf_run(&job, &IO) == MF_BAD_SIGNATURE && fake.opens == 0);
    memcpy(keys[1], public_key, 32);
    job.key_count = 2;
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    ms_fetched_t m;
    CHECK(mode_store_fetched("org.club.relay", &m) && strcmp(m.key_id, MPV_SIGNING_KEY_ID) == 0);
    /* Over 256 KiB, signed as such: refused before the download. */
    box("org.club.huge");
    p = serve("org.club.huge", "1.0.0", "mode", "reduced", SCRIPT);
    sign(p->release, sizeof(p->release), "org.club.huge", "1.0.0", "mode", "reduced", p->archive,
         p->len, MP_BOX_PACKAGE_MAX + 1);
    CHECK(mf_run(&job, &IO) == MF_TOO_BIG && fake.opens == 0);
    /* The archive under another root. */
    box("org.club.relay");
    p = serve("org.club.other", "1.0.0", "role", "reduced", SCRIPT);
    snprintf(p->id, sizeof(p->id), "org.club.relay");
    sign(p->release, sizeof(p->release), "org.club.relay", "1.0.0", "role", "reduced", p->archive,
         p->len, 0);
    CHECK(mf_run(&job, &IO) == MF_BAD_ARCHIVE);
    /* Every archive no reader takes, signed as it is: bad_archive. */
    for (size_t i = 0; i < MPV_BAD_ARCHIVE_COUNT; i += 3) {
        const mpv_archive_t *v = &mpv_bad_archives[i];
        box("org.example.relay");
        p = pkg_add("org.example.relay");
        put_segs(p->archive, v->segs, v->seg_count);
        p->len = v->size;
        sign(p->release, sizeof(p->release), "org.example.relay", "1.2.0-rc.1", "role", "full",
             p->archive, p->len, 0);
        mf_result_t r = mf_run(&job, &IO);
        if (r != MF_BAD_ARCHIVE) {
            fprintf(stderr, "FAIL signed bad archive %s: %s\n", v->name, mf_result_name(r));
            check_failures++;
        }
        check_count++;
        CHECK(!mode_store_has("org.example.relay"));
    }
    /* mode.yaml is never read: one that says something else, or none, changes nothing. */
    box("org.club.relay");
    file_t odd[2] = {{"mode.yaml", "id: org.club.other\nversion: 9.9.9\n"}, {"node.lua", SCRIPT}};
    serve_files("org.club.relay", odd, 2);
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    box("org.club.relay");
    file_t only[1] = {{"node.lua", SCRIPT}};
    serve_files("org.club.relay", only, 1);
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    /* field.lua and other assets travel in the package but are not kept. */
    box("org.club.relay");
    file_t more[5] = {{"assets/images/x.svg", "<svg/>"},
                      {"assets/screens/relay.yaml", SCREEN},
                      {"field.lua", "-- the controller's\n"},
                      {"mode.yaml", "id: org.club.relay\nversion: 1.0.0\n"},
                      {"node.lua", SCRIPT}};
    p = serve_files("org.club.relay", more, 5);
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    char path[256];
    snprintf(path, sizeof(path), "%s/modes/org.club.relay/field.lua", base);
    CHECK(access(path, F_OK) != 0);
    snprintf(path, sizeof(path), "%s/modes/org.club.relay/assets/images/x.svg", base);
    CHECK(access(path, F_OK) != 0);
    CHECK(mode_store_fetched("org.club.relay", &m) && m.bytes == p->len);
}

/* ---- the script, its screens and the composed game in the sandbox --------------------------- */

static void test_load(void)
{
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", "on(\"x\", function(e)\n");
    CHECK(mf_run(&job, &IO) == MF_LOAD && !mode_store_has("org.club.relay"));
    CHECK(reported("org.club.relay", "1.0.0", "load", "-"));
    /* A script that runs away at load: the sandbox's watchdog stops it. */
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", "while true do end\n");
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    /* More than a Reduced box's 64 KB of Lua heap, fine with 256 KB. */
    const char *hungry = "local t = {}\nfor i = 1, 2000 do t[i] = string.rep(\"x\", 16) .. i end\n"
                         "on(\"game.start\", function() end)\n";
    box("org.club.relay");
    serve("org.club.relay", "1.0.0", "role", "reduced", hungry);
    job.reduced = true;
    job.mem_limit = 64u * 1024u;
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    job.reduced = false;
    job.mem_limit = 256u * 1024u;
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    /* A script over the preset buffer. */
    box("org.club.relay");
    static char huge[PRESET_SOURCE_MAX + 100];
    memset(huge, ' ', sizeof(huge) - 1);
    memcpy(huge, "-- x", 4);
    serve("org.club.relay", "1.0.0", "role", "reduced", huge);
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    /* A screen that does not parse, one over 4 KiB. */
    box("org.club.relay");
    file_t bad_screen[2] = {{"assets/screens/x.yaml", "layout: [\n"}, {"node.lua", SCRIPT}};
    serve_files("org.club.relay", bad_screen, 2);
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    box("org.club.relay");
    static char big_screen[5000];
    memset(big_screen, 'a', sizeof(big_screen) - 1);
    file_t big[2] = {{"assets/screens/huge.yaml", big_screen}, {"node.lua", SCRIPT}};
    serve_files("org.club.relay", big, 2);
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    /* Two parts: each fits alone, not together. */
    box("org.club.main+org.club.mod");
    static char half[9000];
    memset(half, ' ', sizeof(half) - 1);
    memcpy(half, "-- a", 4);
    serve("org.club.main", "1.0.0", "mode", "reduced", half);
    serve("org.club.mod", "1.0.0", "modifier", "reduced", half);
    CHECK(mf_run(&job, &IO) == MF_LOAD);
    CHECK(mode_store_has("org.club.main") && !mode_store_has("org.club.mod"));
    CHECK(strcmp(job.part, "org.club.mod") == 0 && job.installed == 1);
}

/* ---- room, replacement, power loss, the boot's check, forgetting ------------------------- */

static void test_room(void)
{
    /* Eight fetched packages at most; the least recently used goes, never one the game needs. */
    box("org.club.p0");
    char id[32];
    for (int i = 0; i < MS_FETCHED_MAX; i++) {
        snprintf(id, sizeof(id), "org.club.p%d", i);
        snprintf(join.mode_id, sizeof(join.mode_id), "%s", id);
        serve(id, "1.0.0", "mode", "reduced", SCRIPT);
        CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    }
    static ms_fetched_t list[MS_FETCHED_MAX + 2];
    CHECK(mode_store_list(list, MS_FETCHED_MAX + 2) == MS_FETCHED_MAX);
    mode_store_touch("org.club.p0+org.club.p2"); /* played lately */
    snprintf(join.mode_id, sizeof(join.mode_id), "org.club.p1+org.club.p8");
    serve("org.club.p8", "1.0.0", "modifier", "reduced", SCRIPT);
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    CHECK(mode_store_has("org.club.p8") && mode_store_has("org.club.p1")); /* needed: kept */
    CHECK(!mode_store_has("org.club.p3"));                                 /* least recent */
    CHECK(mode_store_has("org.club.p0") && mode_store_has("org.club.p2"));
    CHECK(preset_store_find_mode("org.club.p3") < 0);
    /* No room: what is kept is all this game's, and with this part it would be over 512 KiB.
     * Refused before any download. */
    CHECK(!mode_store_make_room(MS_FETCHED_BYTES + 1, NULL, NULL));
    box("org.club.x+org.club.y+org.club.z");
    keep_bytes("org.club.x", "1.0.0", MP_BOX_PACKAGE_MAX);
    keep_bytes("org.club.y", "1.0.0", MP_BOX_PACKAGE_MAX);
    serve("org.club.z", "1.0.0", "mode", "reduced", SCRIPT);
    CHECK(mf_run(&job, &IO) == MF_NO_SPACE && fake.opens == 0);
    CHECK(reported("org.club.z", "1.0.0", "no_space", "org.club.x@1.0.0,org.club.y@1.0.0"));
    /* The bytes: archives together at most 512 KiB. */
    box("org.club.a");
    keep("org.club.b", "1.0.0");
    ms_fetched_t m;
    CHECK(mode_store_fetched("org.club.b", &m));
    CHECK(mode_store_make_room(MS_FETCHED_BYTES - m.bytes, NULL, "org.club.b"));
    CHECK(!mode_store_make_room(MS_FETCHED_BYTES - m.bytes + 1, NULL, "org.club.b"));
    CHECK(mode_store_make_room(MS_FETCHED_BYTES - m.bytes + 1, NULL, NULL)); /* b goes */
    CHECK(!mode_store_has("org.club.b"));

    /* A newer version replaces an older one only at its commit. */
    box("org.club.r");
    keep("org.club.r", "1.0.0");
    keep("org.club.r", "1.1.0");
    CHECK(mode_store_fetched("org.club.r", &m) && strcmp(m.version, "1.1.0") == 0);
    char path[256];
    snprintf(path, sizeof(path), "%s/modes/.old", base);
    CHECK(access(path, F_OK) != 0);
    CHECK(preset_store_find_mode("org.club.r") > 0);

    /* Forgetting: never a built-in mode; all the fetched ones, with their presets. */
    CHECK(!mode_store_remove("org.atalaia.domination"));
    CHECK(mode_store_forget_all() == 1);
    CHECK(!mode_store_has("org.club.r") && preset_store_find_mode("org.club.r") < 0);
}

static void write_text(const char *path, const char *text)
{
    FILE *f = fopen(path, "w");
    CHECK(f != NULL);
    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static void test_power_loss_and_boot(void)
{
    char path[256];
    /* Cut between the commit's renames: .old holds the older version, .new the whole new one,
     * <id> is gone. The next start finishes it. */
    box("org.club.relay");
    snprintf(path, sizeof(path), "%s/modes/.old", base);
    mkdir(path, 0755);
    snprintf(path, sizeof(path), "%s/modes/.new", base);
    mkdir(path, 0755);
    snprintf(path, sizeof(path), "%s/modes/.new/node.lua", base);
    write_text(path, SCRIPT);
    snprintf(path, sizeof(path), "%s/modes/.new/fetched", base);
    write_text(path, "id=org.club.relay\nversion=2.0.0\nkey_id=21fe31dfa154a261\nsha256="
                     "0000000000000000000000000000000000000000000000000000000000000000\n"
                     "bytes=10\nused=3\n");
    CHECK(mode_store_init(base) == 0);
    ms_fetched_t m;
    CHECK(mode_store_fetched("org.club.relay", &m) && strcmp(m.version, "2.0.0") == 0);
    CHECK(mode_store_has("org.club.relay") && preset_store_find_mode("org.club.relay") > 0);
    snprintf(path, sizeof(path), "%s/modes/.old", base);
    CHECK(access(path, F_OK) != 0);
    /* Cut while fetching (no slot written yet): forgotten. */
    snprintf(path, sizeof(path), "%s/modes/.new", base);
    mkdir(path, 0755);
    snprintf(path, sizeof(path), "%s/modes/.new/package.tar", base);
    write_text(path, "half");
    CHECK(mode_store_init(base) == 0);
    snprintf(path, sizeof(path), "%s/modes/.new", base);
    CHECK(access(path, F_OK) != 0);
    static ms_fetched_t list[4];
    CHECK(mode_store_list(list, 4) == 1);
    /* Nothing above the store's folder is reachable through it. */
    CHECK(mode_store_stage_open("../x", "w") == NULL);
    CHECK(mode_store_screen("org.club.relay", 14, "../../x") == NULL);
    CHECK(mode_store_screen("..", 2, "relay") == NULL);

    /* At boot, every kept release is checked again with the firmware's keys. */
    box("org.club.a+org.club.b");
    serve("org.club.a", "1.0.0", "mode", "reduced", SCRIPT);
    serve("org.club.b", "1.0.0", "modifier", "reduced", SCRIPT);
    CHECK(mf_run(&job, &IO) == MF_INSTALLED);
    CHECK(mode_store_verify((const uint8_t(*)[32])keys, 1) == 0);
    CHECK(mode_store_has("org.club.a") && mode_store_has("org.club.b"));
    snprintf(path, sizeof(path), "%s/modes/org.club.b/release", base);
    write_text(path, "not a release\n"); /* a slot whose release no longer reads */
    CHECK(mode_store_verify((const uint8_t(*)[32])keys, 1) == 1);
    CHECK(mode_store_has("org.club.a") && !mode_store_has("org.club.b"));
    uint8_t other[1][32];
    unhex(MPV_OTHER_KEY_HEX, other[0], 32); /* the key left the firmware */
    CHECK(mode_store_verify((const uint8_t(*)[32])other, 1) == 1);
    CHECK(!mode_store_has("org.club.a") && preset_store_find_mode("org.club.a") < 0);
}

void run_mode_fetch_tests(void)
{
    keys_init();
    test_box_check_vectors();
    test_report_vectors();
    test_join_and_network();
    test_download();
    test_release_and_archive();
    test_load();
    test_room();
    test_power_loss_and_boot();
    server_reset();
}
