/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Firmware updates over the air (main/fw_update.c): the shared vectors
 * (protocol/vectors/firmware.json: RFC 8032's Ed25519 tests, signed release texts,
 * versions, image descriptors, reports), then the update job against fakes of
 * the Wi-Fi, the controller's HTTPS answers and the OTA slot: every failure
 * leaves the boot partition alone, and only a complete, hashed, signed image
 * of this variant and board is activated.
 */
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "firmware_vectors.h"
#include "fw_update.h"
#include "monocypher-ed25519.h"

/* The running image's descriptor (fw_desc.c on the device). */
const fw_desc_t atalaia_fw_desc = {
    .magic = {'A', 'T', 'F', 'W'}, .format = 1, .variant = "box", .board = "heltec_v4_3"};

/* ---- the shared vectors -------------------------------------------------------------- */

static void test_rfc8032(void)
{
    CHECK(FW_RFC8032_VECTOR_COUNT == 5);
    for (size_t i = 0; i < FW_RFC8032_VECTOR_COUNT; i++) {
        const fw_rfc8032_vector_t *v = &fw_rfc8032_vectors[i];
        int before = check_failures;
        CHECK(crypto_ed25519_check(v->signature, v->public_key, v->message, v->message_len) == 0);
        uint8_t sig[64];
        memcpy(sig, v->signature, 64);
        sig[i % 64] ^= 0x10;
        CHECK(crypto_ed25519_check(sig, v->public_key, v->message, v->message_len) != 0);
        if (v->message_len > 0) {
            uint8_t *msg = malloc(v->message_len);
            memcpy(msg, v->message, v->message_len);
            msg[0] ^= 1;
            CHECK(crypto_ed25519_check(v->signature, v->public_key, msg, v->message_len) != 0);
            free(msg);
        }
        if (check_failures != before) fprintf(stderr, "  in RFC 8032 vector %s\n", v->name);
    }
}

static void test_release_vectors(void)
{
    uint8_t both[2][32];
    memcpy(both[0], fw_signing_key, 32);
    memcpy(both[1], fw_other_key, 32);
    CHECK(FW_RELEASE_VECTOR_COUNT >= 8);
    for (size_t i = 0; i < FW_RELEASE_VECTOR_COUNT; i++) {
        const fw_release_vector_t *v = &fw_release_vectors[i];
        int before = check_failures;
        fw_release_t rel;
        const char *text = (const char *)v->text;
        CHECK(fw_release_parse(text, v->text_len, &rel));
        CHECK(strcmp(rel.platform, v->platform) == 0 && strcmp(rel.version, v->version) == 0);
        CHECK(rel.size == v->size && strcmp(rel.sha256_hex, v->sha256) == 0);
        CHECK(rel.manifest_len == v->manifest_len);
        CHECK(fw_release_signed(&rel, text, (const uint8_t(*)[32])fw_signing_key, 1) == v->valid);
        /* Two keys (a rotation): what the first key signed still verifies. */
        if (v->valid) CHECK(fw_release_signed(&rel, text, (const uint8_t(*)[32])both, 2));
        CHECK(!fw_release_signed(&rel, text, (const uint8_t(*)[32])both, 0));
        if (check_failures != before) fprintf(stderr, "  in release vector %s\n", v->name);
    }
    /* The release signed by other_key verifies once that key is trusted. */
    const fw_release_vector_t *u = NULL;
    for (size_t i = 0; i < FW_RELEASE_VECTOR_COUNT; i++) {
        if (strcmp(fw_release_vectors[i].name, "untrusted_key") == 0) u = &fw_release_vectors[i];
    }
    CHECK(u != NULL);
    if (u != NULL) {
        fw_release_t rel;
        CHECK(fw_release_parse((const char *)u->text, u->text_len, &rel));
        CHECK(fw_release_signed(&rel, (const char *)u->text, (const uint8_t(*)[32])both, 2));
    }
}

static void test_bad_texts(void)
{
    CHECK(FW_BAD_TEXT_VECTOR_COUNT >= 20);
    for (size_t i = 0; i < FW_BAD_TEXT_VECTOR_COUNT; i++) {
        const fw_text_vector_t *v = &fw_bad_text_vectors[i];
        fw_release_t rel;
        if (fw_release_parse((const char *)v->text, v->text_len, &rel)) {
            fprintf(stderr, "FAIL release text %s was accepted\n", v->name);
            check_failures++;
        }
        check_count++;
    }
}

static void test_versions(void)
{
    const char *const *lists[] = {fw_vec_semver_order, fw_vec_semver_core_order,
                                  fw_vec_version_order};
    const size_t counts[] = {FW_VEC_SEMVER_ORDER_COUNT, FW_VEC_SEMVER_CORE_ORDER_COUNT,
                             FW_VEC_VERSION_ORDER_COUNT};
    for (size_t l = 0; l < 3; l++) {
        for (size_t i = 0; i < counts[l]; i++) {
            CHECK(fw_version_valid(lists[l][i]));
            CHECK(fw_version_compare(lists[l][i], lists[l][i]) == 0);
            for (size_t j = i + 1; j < counts[l]; j++) {
                if (fw_version_compare(lists[l][i], lists[l][j]) >= 0 ||
                    fw_version_compare(lists[l][j], lists[l][i]) <= 0) {
                    fprintf(stderr, "FAIL version order %s < %s\n", lists[l][i], lists[l][j]);
                    check_failures++;
                }
            }
        }
    }
    for (size_t i = 0; i + 1 < FW_VEC_VERSION_EQUAL_COUNT; i += 2) {
        CHECK(fw_version_compare(fw_vec_version_equal[i], fw_vec_version_equal[i + 1]) == 0);
    }
    for (size_t i = 0; i < FW_VEC_VERSION_VALID_COUNT; i++) {
        if (!fw_version_valid(fw_vec_version_valid[i])) {
            fprintf(stderr, "FAIL version %s refused\n", fw_vec_version_valid[i]);
            check_failures++;
        }
    }
    for (size_t i = 0; i < FW_VEC_VERSION_INVALID_COUNT; i++) {
        if (fw_version_valid(fw_vec_version_invalid[i])) {
            fprintf(stderr, "FAIL version \"%s\" accepted\n", fw_vec_version_invalid[i]);
            check_failures++;
        }
    }
    CHECK(!fw_version_valid(NULL));
}

static void test_images(void)
{
    for (size_t i = 0; i < FW_IMAGE_VECTOR_COUNT; i++) {
        const fw_image_vector_t *v = &fw_image_vectors[i];
        fw_image_info_t info;
        bool ok = fw_image_info(v->head, v->head_len, &info);
        CHECK(ok == v->valid);
        if (ok) {
            CHECK(strcmp(info.version, v->version) == 0 && strcmp(info.project, v->project) == 0);
            CHECK(strcmp(info.variant, v->variant) == 0 && strcmp(info.board, v->board) == 0);
        }
        if (ok != v->valid) fprintf(stderr, "  in image vector %s\n", v->name);
    }
}

static atalaia_join_t link_join(void)
{
    atalaia_join_t j;
    memset(&j, 0, sizeof(j));
    j.game_id = 4242;
    j.node_id = 7;
    j.controller_id = 0;
    j.channel_hz = 869525000u;
    j.max_hops = 2;
    snprintf(j.teams[0], sizeof(j.teams[0]), "red");
    j.team_count = 1;
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.domination");
    snprintf(j.role, sizeof(j.role), "zone");
    memcpy(j.game_key, fw_report_game_key, 16);
    j.has_ca = true;
    memset(j.ca_sha256, 0xCA, 32);
    j.url_count = 2;
    snprintf(j.urls[0], sizeof(j.urls[0]), "https://10.42.0.1:8443");
    snprintf(j.urls[1], sizeof(j.urls[1]), "https://atalaia.local:8443");
    return j;
}

static void test_reports(void)
{
    atalaia_join_t j = link_join();
    for (size_t i = 0; i < FW_REPORT_VECTOR_COUNT; i++) {
        const fw_report_vector_t *v = &fw_report_vectors[i];
        j.game_id = v->game;
        j.node_id = v->node;
        fw_result_t r = FW_INSTALLED;
        while (strcmp(fw_result_name(r), v->result) != 0 && r <= FW_CANCELLED) r++;
        CHECK(r <= FW_CANCELLED);
        char body[FW_REPORT_MAX], mac[65];
        size_t n = fw_report(&j, v->release, r, v->version, body, sizeof(body), mac);
        CHECK(n == strlen(v->body) && strcmp(body, v->body) == 0);
        CHECK(strcmp(mac, v->mac) == 0);
        CHECK(fw_report(&j, v->release, r, v->version, body, 20, mac) == 0); /* does not fit */
    }
    CHECK(strcmp(fw_result_name((fw_result_t)99), "?") == 0);
}

static void test_keys_and_offers(void)
{
    uint8_t keys[FW_KEYS_MAX][32];
    char text[400];
    snprintf(text, sizeof(text), " %s, %s ", FW_SIGNING_KEY_HEX, FW_OTHER_KEY_HEX);
    CHECK(fw_keys_parse(text, keys, FW_KEYS_MAX) == 2);
    CHECK(memcmp(keys[0], fw_signing_key, 32) == 0 && memcmp(keys[1], fw_other_key, 32) == 0);
    for (char *c = text; *c; c++) {
        if (*c >= 'a' && *c <= 'f') *c = (char)(*c - 32);
    }
    CHECK(fw_keys_parse(text, keys, FW_KEYS_MAX) == 2); /* upper-case hex too */
    CHECK(fw_keys_parse("", keys, FW_KEYS_MAX) == 0);
    CHECK(fw_keys_parse(NULL, keys, FW_KEYS_MAX) == 0);
    CHECK(fw_keys_parse("abcd", keys, FW_KEYS_MAX) == -1);
    snprintf(text, sizeof(text), "%sx", FW_SIGNING_KEY_HEX);
    CHECK(fw_keys_parse(text, keys, FW_KEYS_MAX) == -1);
    snprintf(text, sizeof(text), "%s %s", FW_SIGNING_KEY_HEX, FW_SIGNING_KEY_HEX);
    CHECK(fw_keys_parse(text, keys, 1) == -1); /* more than fit */

    char id[FW_RELEASE_ID_LEN + 1], version[FW_VERSION_MAX + 1];
    CHECK(fw_offer_parse("{\"id\":\"0123456789abcdef\",\"version\":\"0.3.0\"}", id, version));
    CHECK(strcmp(id, "0123456789abcdef") == 0 && strcmp(version, "0.3.0") == 0);
    CHECK(fw_offer_parse("{\"version\":\"0.3.0-rc.1\",\"id\":\"0123456789abcdef\"}", id, version));
    CHECK(!fw_offer_parse("{\"id\":\"0123456789abcde\",\"version\":\"0.3.0\"}", id, version));
    CHECK(!fw_offer_parse("{\"id\":\"0123456789abcdef0\",\"version\":\"0.3.0\"}", id, version));
    CHECK(!fw_offer_parse("{\"id\":\"0123456789ABCDEF\",\"version\":\"0.3.0\"}", id, version));
    CHECK(!fw_offer_parse("{\"id\":\"0123456789abcdef\",\"version\":\"0.3\"}", id, version));
    CHECK(!fw_offer_parse("{\"id\":\"0123456789abcdef\"}", id, version));
    CHECK(!fw_offer_parse(NULL, id, version));
}

/* ---- the job, with fakes --------------------------------------------------------------- */

#define IMG_SIZE 9000u

typedef struct {
    /* The controller. */
    bool wifi;
    int answering_url; /* index of the address that answers; -1: none */
    char text[FW_RELEASE_TEXT_MAX + 1];
    uint8_t image[IMG_SIZE + 16];
    size_t image_len; /* what the controller sends */
    int64_t length;   /* its Content-Length (-1: none) */
    size_t chunk;     /* bytes per read */
    size_t fail_at;   /* the read fails once this many bytes went (0: never) */
    size_t cancel_at; /* a game starts once this many bytes went (0: never) */
    size_t sent;
    bool open;
    /* The slot. */
    int begins, ends, activates, aborts;
    size_t written;
    bool fail_begin, fail_end, fail_activate;
    /* What happened. */
    int net_ups, net_downs, gets, posts;
    char got_base[80];
    char report[FW_REPORT_MAX];
    char report_mac[65];
    char post_base[80];
} fake_t;

static fake_t F;

static bool f_net_up(void *ctx)
{
    (void)ctx;
    F.net_ups++;
    return F.wifi;
}
static void f_net_down(void *ctx)
{
    (void)ctx;
    F.net_downs++;
}
static int f_get_text(void *ctx, const char *base, const char *path, char *buf, size_t cap)
{
    (void)ctx;
    F.gets++;
    atalaia_join_t j = link_join();
    if (F.answering_url < 0 || strcmp(base, j.urls[F.answering_url]) != 0) return -1;
    if (strstr(path, "/api/v1/firmware/") != path || strstr(path, "/release") == NULL) return -1;
    size_t n = strlen(F.text);
    if (n >= cap) return -1;
    memcpy(buf, F.text, n + 1);
    snprintf(F.got_base, sizeof(F.got_base), "%s", base);
    return (int)n;
}
static bool f_open(void *ctx, const char *base, const char *path, int64_t *length)
{
    (void)ctx;
    if (strcmp(base, F.got_base) != 0 || strstr(path, "/image") == NULL) return false;
    F.open = true;
    F.sent = 0;
    *length = F.length;
    return true;
}
static int f_read(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    if (!F.open) return -1;
    if (F.fail_at && F.sent >= F.fail_at) return -1;
    size_t n = F.image_len - F.sent;
    if (n > F.chunk) n = F.chunk;
    if (n > cap) n = cap;
    memcpy(buf, F.image + F.sent, n);
    F.sent += n;
    return (int)n;
}
static void f_close(void *ctx)
{
    (void)ctx;
    F.open = false;
}
static void f_post(void *ctx, const char *base, const char *path, const char *body, const char *mac)
{
    (void)ctx;
    CHECK(strcmp(path, "/api/v1/firmware/report") == 0);
    F.posts++;
    snprintf(F.post_base, sizeof(F.post_base), "%s", base);
    snprintf(F.report, sizeof(F.report), "%s", body);
    snprintf(F.report_mac, sizeof(F.report_mac), "%s", mac);
}
static bool f_cancelled(void *ctx)
{
    (void)ctx;
    return F.cancel_at && F.sent >= F.cancel_at;
}
static int f_begin(void *ctx, uint32_t size)
{
    (void)ctx;
    F.begins++;
    CHECK(size == IMG_SIZE);
    return F.fail_begin ? -1 : 0;
}
static int f_write(void *ctx, const uint8_t *data, size_t len)
{
    (void)ctx;
    CHECK(F.begins == 1 && F.ends == 0);
    CHECK(F.written + len <= IMG_SIZE && memcmp(data, F.image + F.written, len) == 0);
    F.written += len;
    return 0;
}
static int f_end(void *ctx)
{
    (void)ctx;
    F.ends++;
    return F.fail_end ? -1 : 0;
}
static int f_activate(void *ctx)
{
    (void)ctx;
    F.activates++;
    CHECK(F.ends == 1 && F.written == IMG_SIZE);
    return F.fail_activate ? -1 : 0;
}
static void f_abort(void *ctx)
{
    (void)ctx;
    F.aborts++;
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
    .flash = {f_begin, f_write, f_end, f_activate, f_abort},
    .ctx = NULL,
};

static uint8_t seed_secret[64], seed_public[32];

/* A box image of IMG_SIZE bytes declaring version, variant and board. */
static void make_image(const char *version, const char *variant, const char *board)
{
    memset(F.image, 0, sizeof(F.image));
    for (size_t i = FW_IMAGE_HEAD; i < IMG_SIZE; i++) F.image[i] = (uint8_t)(i * 7u + 3u);
    F.image[0] = 0xE9;
    F.image[1] = 4;
    uint8_t *d = F.image + FW_APP_DESC_OFFSET;
    d[0] = 0x32;
    d[1] = 0x54;
    d[2] = 0xCD;
    d[3] = 0xAB;
    memcpy(d + 16, version, strlen(version));
    memcpy(d + 48, FW_PROJECT_NAME, strlen(FW_PROJECT_NAME));
    uint8_t *a = F.image + FW_DESC_OFFSET;
    memcpy(a, "ATFW", 4);
    a[4] = 1;
    memcpy(a + 8, variant, strlen(variant));
    memcpy(a + 20, board, strlen(board));
    F.image_len = IMG_SIZE;
    F.length = IMG_SIZE;
}

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/* The release text for F.image (or for claimed_size bytes), signed with the vectors' key. */
static void make_release(const char *platform, const char *version, uint32_t claimed_size,
                         char id_out[FW_RELEASE_ID_LEN + 1])
{
    uint8_t h[32];
    atalaia_sha256(F.image, IMG_SIZE, h);
    char hex[65];
    for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", h[i]);
    int n = snprintf(F.text, sizeof(F.text), "%s\nplatform=%s\nversion=%s\nsize=%u\nsha256=%s\n",
                     FW_MANIFEST_HEADER, platform, version, (unsigned)claimed_size, hex);
    uint8_t sig[64];
    crypto_ed25519_sign(sig, seed_secret, (const uint8_t *)F.text, (size_t)n);
    char b64[89];
    size_t o = 0;
    for (size_t i = 0; i < 63; i += 3) {
        uint32_t v = (uint32_t)sig[i] << 16 | (uint32_t)sig[i + 1] << 8 | sig[i + 2];
        b64[o++] = B64[v >> 18];
        b64[o++] = B64[(v >> 12) & 63];
        b64[o++] = B64[(v >> 6) & 63];
        b64[o++] = B64[v & 63];
    }
    b64[o++] = B64[sig[63] >> 2];
    b64[o++] = B64[(sig[63] & 3) << 4];
    b64[o++] = '=';
    b64[o++] = '=';
    b64[o] = '\0';
    snprintf(F.text + n, sizeof(F.text) - (size_t)n, "signature=%s\n", b64);
    memcpy(id_out, hex, FW_RELEASE_ID_LEN);
    id_out[FW_RELEASE_ID_LEN] = '\0';
}

static atalaia_join_t job_join;

/* A ready job and controller: version 0.3.0 for a box running 0.2.0. */
static void setup(fw_job_t *job)
{
    memset(&F, 0, sizeof(F));
    F.wifi = true;
    F.answering_url = 0;
    F.chunk = 1024;
    make_image("0.3.0", "box", "heltec_v4_3");
    memset(job, 0, sizeof(*job));
    make_release("esp32s3", "0.3.0", IMG_SIZE, job->id);
    snprintf(job->version, sizeof(job->version), "0.3.0");
    job->platform = "esp32s3";
    job->running_version = "0.2.0";
    job->desc = &atalaia_fw_desc;
    job->keys = (const uint8_t(*)[32])fw_signing_key;
    job->key_count = 1;
    job->slot_size = 0x200000;
    job->battery_pct = -1;
    job->min_battery_pct = 30;
    job_join = link_join();
    job->join = &job_join;
}

/* Nothing that changes the next boot happened. */
static bool untouched(void)
{
    return F.activates == 0;
}

static void test_job_installs(void)
{
    static const size_t chunks[] = {1, 7, 323, 324, 325, 1024, 4096, 100000};
    for (size_t c = 0; c < sizeof(chunks) / sizeof(chunks[0]); c++) {
        fw_job_t job;
        setup(&job);
        F.chunk = chunks[c];
        int before = check_failures;
        CHECK(fw_update_run(&job, &IO) == FW_INSTALLED);
        CHECK(F.begins == 1 && F.written == IMG_SIZE && F.ends == 1 && F.activates == 1);
        CHECK(F.aborts == 0 && job.written == IMG_SIZE && strcmp(job.base, job_join.urls[0]) == 0);
        CHECK(F.net_ups == 1 && F.net_downs == 1);
        /* The report: installed, the new version, signed with the game key. */
        CHECK(F.posts == 1 && strstr(F.report, "result=installed\nversion=0.3.0\n") != NULL);
        uint8_t mac[32];
        atalaia_hmac_sha256(job_join.game_key, 16, (const uint8_t *)F.report, strlen(F.report),
                            mac);
        char hex[65];
        for (int i = 0; i < 32; i++) snprintf(hex + 2 * i, 3, "%02x", mac[i]);
        CHECK(strcmp(hex, F.report_mac) == 0);
        if (check_failures != before) fprintf(stderr, "  with %zu-byte reads\n", chunks[c]);
    }
    /* No Content-Length (chunked): the signed size still bounds it. */
    fw_job_t job;
    setup(&job);
    F.length = -1;
    CHECK(fw_update_run(&job, &IO) == FW_INSTALLED && F.activates == 1);
    /* The first address does not answer, the second does: it is used for all of it. */
    setup(&job);
    F.answering_url = 1;
    CHECK(fw_update_run(&job, &IO) == FW_INSTALLED);
    CHECK(strcmp(job.base, job_join.urls[1]) == 0 && strcmp(F.post_base, job_join.urls[1]) == 0);
    /* A newer pre-release over a release, and a second key (rotation). */
    setup(&job);
    make_image("0.3.0-rc.1", "box", "heltec_v4_3");
    make_release("esp32s3", "0.3.0-rc.1", IMG_SIZE, job.id);
    snprintf(job.version, sizeof(job.version), "0.3.0-rc.1");
    uint8_t two[2][32];
    memcpy(two[0], fw_other_key, 32);
    memcpy(two[1], fw_signing_key, 32);
    job.keys = (const uint8_t(*)[32])two;
    job.key_count = 2;
    CHECK(fw_update_run(&job, &IO) == FW_INSTALLED);
}

static void test_job_prechecks(void)
{
    fw_job_t job;
    setup(&job);
    job.playing = true;
    CHECK(fw_update_run(&job, &IO) == FW_BUSY && F.net_ups == 0);
    setup(&job);
    job.key_count = 0;
    CHECK(fw_update_run(&job, &IO) == FW_NO_KEY && F.net_ups == 0);
    setup(&job);
    job_join.has_ca = false;
    CHECK(fw_update_run(&job, &IO) == FW_NO_LINK && F.net_ups == 0);
    setup(&job);
    job_join.url_count = 0;
    CHECK(fw_update_run(&job, &IO) == FW_NO_LINK);
    setup(&job);
    job.join = NULL; /* not in a game */
    CHECK(fw_update_run(&job, &IO) == FW_NO_LINK);
    setup(&job);
    job.running_version = "0.3.0"; /* the same version */
    CHECK(fw_update_run(&job, &IO) == FW_NOT_NEWER && F.net_ups == 0);
    setup(&job);
    job.running_version = "0.4.0"; /* a lower one: anti-rollback */
    CHECK(fw_update_run(&job, &IO) == FW_NOT_NEWER);
    setup(&job);
    job.running_version = "not-a-version";
    CHECK(fw_update_run(&job, &IO) == FW_NOT_NEWER);
    setup(&job);
    job.battery_pct = 29;
    CHECK(fw_update_run(&job, &IO) == FW_BATTERY && F.net_ups == 0);
    setup(&job);
    job.battery_pct = 30;
    CHECK(fw_update_run(&job, &IO) == FW_INSTALLED);
    setup(&job);
    job.id[0] = '\0';
    CHECK(fw_update_run(&job, &IO) == FW_BAD_OFFER);
}

static void test_job_refusals(void)
{
    fw_job_t job;
    /* No Wi-Fi. */
    setup(&job);
    F.wifi = false;
    CHECK(fw_update_run(&job, &IO) == FW_NO_WIFI && F.gets == 0 && F.net_downs == 1);
    /* No address answers: nothing to report to. */
    setup(&job);
    F.answering_url = -1;
    CHECK(fw_update_run(&job, &IO) == FW_UNREACHABLE && F.gets == 2 && F.posts == 0);
    /* Signed by a key this firmware does not trust. */
    setup(&job);
    job.keys = (const uint8_t(*)[32])fw_other_key;
    CHECK(fw_update_run(&job, &IO) == FW_BAD_SIGNATURE && F.begins == 0 && untouched());
    CHECK(F.posts == 1 && strstr(F.report, "result=bad_signature\nversion=0.2.0\n") != NULL);
    /* A tampered release text: the version changed after signing. */
    setup(&job);
    char *v = strstr(F.text, "version=0.3.0");
    v[12] = '1';
    snprintf(job.version, sizeof(job.version), "0.3.1");
    CHECK(fw_update_run(&job, &IO) == FW_BAD_SIGNATURE && F.begins == 0);
    /* The release is not the one offered: another version, another id. */
    setup(&job);
    snprintf(job.version, sizeof(job.version), "0.3.1");
    CHECK(fw_update_run(&job, &IO) == FW_BAD_RELEASE && F.begins == 0);
    setup(&job);
    job.id[0] = job.id[0] == '0' ? '1' : '0';
    CHECK(fw_update_run(&job, &IO) == FW_BAD_RELEASE && F.begins == 0);
    /* Malformed. */
    setup(&job);
    F.text[3] = 'X';
    CHECK(fw_update_run(&job, &IO) == FW_BAD_RELEASE);
    /* Signed, but for another platform. */
    setup(&job);
    make_release("esp32", "0.3.0", IMG_SIZE, job.id);
    CHECK(fw_update_run(&job, &IO) == FW_WRONG_PLATFORM && F.begins == 0);
    /* Larger than the slot. */
    setup(&job);
    job.slot_size = IMG_SIZE - 1;
    CHECK(fw_update_run(&job, &IO) == FW_TOO_BIG && F.begins == 0);
}

static void test_job_image_checks(void)
{
    fw_job_t job;
    /* The image says another version than its signed release: nothing is written. */
    setup(&job);
    make_image("0.2.9", "box", "heltec_v4_3");
    make_release("esp32s3", "0.3.0", IMG_SIZE, job.id);
    CHECK(fw_update_run(&job, &IO) == FW_BAD_IMAGE && F.begins == 0 && untouched());
    /* Another board, another variant. */
    setup(&job);
    make_image("0.3.0", "box", "heltec_v4_2");
    make_release("esp32s3", "0.3.0", IMG_SIZE, job.id);
    CHECK(fw_update_run(&job, &IO) == FW_WRONG_BOARD && F.begins == 0);
    setup(&job);
    make_image("0.3.0", "box-bench", "heltec_v4_3");
    make_release("esp32s3", "0.3.0", IMG_SIZE, job.id);
    CHECK(fw_update_run(&job, &IO) == FW_WRONG_BOARD && F.begins == 0);
    /* Not an Atalaia image. */
    setup(&job);
    F.image[FW_DESC_OFFSET] = 'X';
    make_release("esp32s3", "0.3.0", IMG_SIZE, job.id);
    CHECK(fw_update_run(&job, &IO) == FW_BAD_IMAGE && F.begins == 0);
    /* A different byte after the header: same size, another hash. */
    setup(&job);
    F.image[5000] ^= 0x80;
    CHECK(fw_update_run(&job, &IO) == FW_BAD_HASH && F.begins == 1 && F.aborts == 1 && untouched());
    CHECK(F.ends == 0);
}

static void test_job_interrupted(void)
{
    fw_job_t job;
    /* The connection breaks half way: the slot's write is dropped, the boot unchanged. */
    setup(&job);
    F.fail_at = 4096;
    CHECK(fw_update_run(&job, &IO) == FW_DOWNLOAD && F.aborts == 1 && untouched() && F.ends == 0);
    CHECK(F.net_downs == 1 && strstr(F.report, "result=download\n") != NULL);
    /* It breaks before the header is complete: nothing was even started. */
    setup(&job);
    F.fail_at = 100;
    F.chunk = 50;
    CHECK(fw_update_run(&job, &IO) == FW_DOWNLOAD && F.begins == 0 && F.aborts == 0);
    /* The stream ends early. */
    setup(&job);
    F.image_len = IMG_SIZE - 1;
    F.length = -1;
    CHECK(fw_update_run(&job, &IO) == FW_DOWNLOAD && F.aborts == 1 && untouched());
    /* More bytes than signed. */
    setup(&job);
    F.image_len = IMG_SIZE + 10;
    F.length = -1;
    CHECK(fw_update_run(&job, &IO) == FW_DOWNLOAD && F.aborts == 1 && untouched());
    /* A Content-Length other than the signed size: refused before the slot is touched. */
    setup(&job);
    F.length = IMG_SIZE + 1;
    CHECK(fw_update_run(&job, &IO) == FW_DOWNLOAD && F.begins == 0);
    /* A game starts during the download. */
    setup(&job);
    F.cancel_at = 2048;
    CHECK(fw_update_run(&job, &IO) == FW_CANCELLED && F.aborts == 1 && untouched());
    /* The slot fails: to begin, to validate (esp_ota_end), to activate. */
    setup(&job);
    F.fail_begin = true;
    CHECK(fw_update_run(&job, &IO) == FW_FLASH && untouched());
    setup(&job);
    F.fail_end = true;
    CHECK(fw_update_run(&job, &IO) == FW_FLASH && untouched() && F.aborts == 0);
    setup(&job);
    F.fail_activate = true;
    CHECK(fw_update_run(&job, &IO) == FW_FLASH && F.activates == 1 && F.aborts == 0);
    CHECK(strstr(F.report, "result=flash\nversion=0.2.0\n") != NULL);
}

static void test_self_test(void)
{
    CHECK(fw_update_self_test((const uint8_t(*)[32])fw_signing_key, 1));
    CHECK(!fw_update_self_test((const uint8_t(*)[32])fw_signing_key, 0)); /* no key: roll back */
    CHECK(!fw_update_self_test(NULL, 1));
}

void run_fw_update_tests(void)
{
    uint8_t seed[32]; /* Monocypher wipes the seed it is given */
    memcpy(seed, fw_signing_seed, sizeof(seed));
    crypto_ed25519_key_pair(seed_secret, seed_public, seed);
    CHECK(memcmp(seed_public, fw_signing_key, 32) == 0);
    test_rfc8032();
    test_release_vectors();
    test_bad_texts();
    test_versions();
    test_images();
    test_reports();
    test_keys_and_offers();
    test_job_installs();
    test_job_prechecks();
    test_job_refusals();
    test_job_image_checks();
    test_job_interrupted();
    test_self_test();
}
