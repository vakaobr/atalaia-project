/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box fetching the signed mode packages a game needs (mode_fetch.h). The
 * Python reference of each check and of the report is box_check_release,
 * box_check_archive and report_body in controller/atalaia_controller/mode_package.py;
 * both are tested against protocol/vectors/mode_package.json (box_checks, reports).
 */
#include "mode_fetch.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/node.h"
#include "atalaia/screen_template.h"
#include "mode_store.h"
#include "preset_store.h"

static const char *const RESULT_NAMES[] = {
    "installed",   "no_wifi",       "unreachable", "not_offered", "download", "no_key",
    "bad_release", "bad_signature", "kind",        "tier",        "builtin",  "too_big",
    "bad_hash",    "bad_archive",   "load",        "no_space",    "storage",  "cancelled",
};

const char *mf_result_name(mf_result_t r)
{
    size_t i = (size_t)r;
    return i < sizeof(RESULT_NAMES) / sizeof(RESULT_NAMES[0]) ? RESULT_NAMES[i] : "?";
}

void mf_path(char *buf, size_t cap, const char *id, const char *what)
{
    snprintf(buf, cap, "/api/v1/mode-packages/%s/%s", id, what);
}

/* ---- the report ------------------------------------------------------------------------- */

static int by_id(const void *a, const void *b)
{
    return strcmp(((const ms_fetched_t *)a)->id, ((const ms_fetched_t *)b)->id);
}

size_t mf_report(const atalaia_join_t *join, const char *part, mf_result_t result,
                 const char *version, char *body, size_t cap, char mac_hex[65])
{
    int n = snprintf(body, cap,
                     "atalaia-mode-report-v1\ngame=%u\nnode=%u\nmode=%s\nversion=%s\nresult=%s\n"
                     "kept=",
                     (unsigned)join->game_id, (unsigned)join->node_id, part,
                     version != NULL && version[0] ? version : "-", mf_result_name(result));
    if (n <= 0 || (size_t)n >= cap) return 0;
    size_t len = (size_t)n;
    ms_fetched_t *kept = malloc(MS_FETCHED_MAX * sizeof(ms_fetched_t));
    int count = kept != NULL ? mode_store_list(kept, MS_FETCHED_MAX) : 0;
    qsort(kept, (size_t)count, sizeof(ms_fetched_t), by_id);
    for (int i = 0; i < count; i++) {
        n = snprintf(body + len, cap - len, "%s%s@%s", i ? "," : "", kept[i].id, kept[i].version);
        if (n <= 0 || len + (size_t)n >= cap) {
            free(kept);
            return 0;
        }
        len += (size_t)n;
    }
    free(kept);
    n = snprintf(body + len, cap - len, "%s\n", count ? "" : "-");
    if (n <= 0 || len + (size_t)n >= cap) return 0;
    len += (size_t)n;
    uint8_t mac[32];
    atalaia_hmac_sha256(join->game_key, ATALAIA_JOIN_GAME_KEY, (const uint8_t *)body, len, mac);
    for (int i = 0; i < 32; i++) snprintf(mac_hex + 2 * i, 3, "%02x", mac[i]);
    return len;
}

/* ---- parts ------------------------------------------------------------------------------- */

/* The i-th part of the mode id into out; false past the last or for a part that is not an id. */
static bool part_at(const char *mode_id, int index, char out[MP_ID_MAX + 1])
{
    const char *p = mode_id;
    for (int i = 0; i < index; i++) {
        p = strchr(p, '+');
        if (p == NULL) return false;
        p++;
    }
    size_t n = strcspn(p, "+");
    if (!mp_id_valid(p, n)) return false;
    memcpy(out, p, n);
    out[n] = '\0';
    return true;
}

static int part_count(const char *mode_id)
{
    int n = 1;
    for (const char *p = mode_id; *p; p++) {
        if (*p == '+') n++;
    }
    return n;
}

int mf_missing(const atalaia_join_t *j)
{
    if (j == NULL) return -1;
    int parts = part_count(j->mode_id);
    if (parts > MF_PARTS_MAX) return -1;
    int missing = 0;
    char id[MP_ID_MAX + 1];
    for (int i = 0; i < parts; i++) {
        if (!part_at(j->mode_id, i, id)) return -1;
        if (!mode_store_has(id)) missing++;
    }
    return missing;
}

bool mf_join_can_fetch(const atalaia_join_t *j, size_t key_count)
{
    return j != NULL && j->fetch_modes && j->has_ca && j->url_count > 0 && key_count > 0 &&
           mf_missing(j) > 0;
}

/* ---- one part ----------------------------------------------------------------------------- */

/* The release text of part, from job->base, or from the first address that answers (which
 * becomes job->base). get_text: -1 no answer, -2 an answer other than 200, -3 a 200 longer than
 * a release text may be. */
static mf_result_t fetch_release(mf_job_t *job, const fw_io_t *io, const char *part, char *text,
                                 size_t cap, int *len)
{
    char path[MP_ID_MAX + 40];
    mf_path(path, sizeof(path), part, "release");
    for (uint8_t u = 0; u < job->join->url_count; u++) {
        if (io->cancelled(io->ctx)) return MF_CANCELLED;
        const char *base = job->base[0] ? job->base : job->join->urls[u];
        int n = io->get_text(io->ctx, base, path, text, cap);
        if ((n > 0 || n <= -2) && base != job->base) { /* it answered: the address to use */
            snprintf(job->base, sizeof(job->base), "%s", base);
        }
        if (n > 0) {
            *len = n;
            return MF_INSTALLED;
        }
        if (n == -2) return MF_NOT_OFFERED;
        if (n <= -3) return MF_BAD_RELEASE;
        if (job->base[0] && base == job->base) break; /* the controller answered before */
    }
    return MF_UNREACHABLE;
}

/* box_check_release, after no_key (checked before any network). */
static mf_result_t check_release(mf_job_t *job, const char *part, const char *text, size_t len)
{
    mp_release_t *rel = &job->release;
    if (!mp_release_parse(text, len, rel) || strcmp(rel->id, part) != 0) {
        memset(rel, 0, sizeof(*rel)); /* not this part's: no version is reported */
        return MF_BAD_RELEASE;
    }
    int signer = mp_release_signer(rel, text, job->keys, job->key_count);
    if (signer < 0) return MF_BAD_SIGNATURE;
    mp_key_id(job->keys[signer], job->key_id);
    if (rel->kind == MP_KIND_SCENARIO) return MF_KIND;
    if (rel->tier == MP_TIER_FULL && job->reduced) return MF_TIER;
    if (job->builtin != NULL && job->builtin(rel->id)) return MF_BUILTIN;
    if (rel->size > MP_BOX_PACKAGE_MAX) return MF_TOO_BIG;
    return MF_INSTALLED;
}

/* The archive into .new/package.tar, hashed as it streams: nothing in it is read before its size
 * and SHA-256 are the signed ones. open: false with *length -2 when the controller answered
 * other than 200. */
static mf_result_t download(mf_job_t *job, const fw_io_t *io, const char *part)
{
    char path[MP_ID_MAX + 40];
    mf_path(path, sizeof(path), part, "package");
    int64_t length = -1;
    if (!io->open(io->ctx, job->base, path, &length)) {
        return length == -2 ? MF_NOT_OFFERED : MF_DOWNLOAD;
    }
    mf_result_t r = MF_INSTALLED;
    if (length >= 0 && length != (int64_t)job->release.size) r = MF_DOWNLOAD;
    FILE *f = r == MF_INSTALLED ? mode_store_stage_open("package.tar", "wb") : NULL;
    if (r == MF_INSTALLED && f == NULL) r = MF_STORAGE;
    atalaia_sha256_t sha;
    atalaia_sha256_init(&sha);
    uint32_t got = 0;
    while (r == MF_INSTALLED) {
        if (io->cancelled(io->ctx)) {
            r = MF_CANCELLED;
            break;
        }
        int n = io->read(io->ctx, job->buf, job->buf_cap);
        if (n < 0) r = MF_DOWNLOAD;
        if (n <= 0) break;
        if ((uint64_t)got + (uint64_t)n > job->release.size) {
            r = MF_DOWNLOAD; /* more than the signed size */
            break;
        }
        got += (uint32_t)n;
        atalaia_sha256_update(&sha, job->buf, (size_t)n);
        if (fwrite(job->buf, 1, (size_t)n, f) != (size_t)n) r = MF_STORAGE;
        if (io->progress != NULL) io->progress(io->ctx, got, job->release.size);
    }
    io->close(io->ctx);
    if (f != NULL && fclose(f) != 0 && r == MF_INSTALLED) r = MF_STORAGE;
    /* Fewer bytes than announced: the connection broke; without a Content-Length, the archive
     * that came is not the signed one (box_check_archive). */
    if (r == MF_INSTALLED && got != job->release.size) r = length >= 0 ? MF_DOWNLOAD : MF_BAD_HASH;
    if (r == MF_INSTALLED) {
        uint8_t digest[32];
        atalaia_sha256_final(&sha, digest);
        if (memcmp(digest, job->release.sha256, 32) != 0) r = MF_BAD_HASH;
    }
    return r;
}

/* Reading the archive back: what is kept goes into .new; each screen is also gathered whole in
 * scratch to be parsed (the load check, after the archive is known canonical). */
typedef struct {
    mf_job_t *job;
    FILE *out;
    bool script;
    bool screen; /* the current file is a screen */
    size_t screen_len;
    bool screens_bad; /* a screen too long or that does not parse */
    mf_result_t why;  /* why a callback stopped the reader */
    atalaia_tpl_t *tpl;
} extract_t;

static bool screen_file(const char *name)
{
    if (strncmp(name, "assets/screens/", 15) != 0) return false;
    const char *base = name + 15;
    size_t n = strlen(base);
    return strchr(base, '/') == NULL && n > 5 && strcmp(base + n - 5, ".yaml") == 0;
}

static bool on_begin(void *ctx, const char *name, uint32_t size)
{
    extract_t *x = (extract_t *)ctx;
    bool script = strcmp(name, "node.lua") == 0;
    x->screen = screen_file(name);
    x->screen_len = 0;
    if (!script && !x->screen) return true; /* mode.yaml, field.lua, other assets: not kept */
    if (x->screen && size > MS_SCREEN_MAX) x->screens_bad = true;
    x->out = mode_store_stage_open(name, "wb");
    if (x->out == NULL) {
        x->why = MF_STORAGE;
        return false;
    }
    x->script = x->script || script;
    return true;
}

static bool on_data(void *ctx, const uint8_t *data, size_t len)
{
    extract_t *x = (extract_t *)ctx;
    if (x->out != NULL && fwrite(data, 1, len, x->out) != len) {
        x->why = MF_STORAGE;
        return false;
    }
    if (x->screen && x->screen_len + len <= MS_SCREEN_MAX) {
        memcpy(x->job->scratch + x->screen_len, data, len);
        x->screen_len += len;
    }
    return true;
}

static bool on_end(void *ctx)
{
    extract_t *x = (extract_t *)ctx;
    if (x->screen && !x->screens_bad) {
        char err[8];
        if (x->tpl == NULL ||
            !atalaia_tpl_parse(x->tpl, x->job->scratch, x->screen_len, err, sizeof(err))) {
            x->screens_bad = true;
        }
    }
    x->screen = false;
    if (x->out != NULL) {
        int rc = fclose(x->out);
        x->out = NULL;
        if (rc != 0) {
            x->why = MF_STORAGE;
            return false;
        }
    }
    return true;
}

/* box_check_archive's form (bad_archive), then the screens (load). */
static mf_result_t extract(mf_job_t *job, bool *screens_bad)
{
    extract_t x;
    memset(&x, 0, sizeof(x));
    x.job = job;
    x.tpl = malloc(sizeof(atalaia_tpl_t)); /* a few KB, only while the archive is read */
    FILE *f = mode_store_stage_open("package.tar", "rb");
    if (f == NULL || x.tpl == NULL) {
        if (f != NULL) fclose(f);
        free(x.tpl);
        return MF_STORAGE;
    }
    const mp_tar_ops_t ops = {on_begin, on_data, on_end, &x};
    mp_tar_t tar; /* 0.8 KB, on the fetch task's stack */
    mp_tar_init(&tar, job->release.id, job->release.size > MP_BLOCK ? job->release.size : MP_BLOCK,
                &ops);
    mp_tar_result_t t = MP_TAR_OK;
    for (;;) {
        size_t n = fread(job->buf, 1, job->buf_cap, f);
        if (n == 0) break;
        t = mp_tar_feed(&tar, job->buf, n);
        if (t != MP_TAR_OK) break;
    }
    fclose(f);
    if (t == MP_TAR_OK) t = mp_tar_finish(&tar);
    if (x.out != NULL) fclose(x.out);
    free(x.tpl);
    mode_store_stage_remove("package.tar");
    *screens_bad = x.screens_bad;
    if (t == MP_TAR_STOPPED) return x.why;
    if (t != MP_TAR_OK || !x.script) return MF_BAD_ARCHIVE;
    return MF_INSTALLED;
}

/* The staged script loads in a fresh sandbox with this box's heap, and the game's composed
 * script (every part already on the box, and this one) fits the preset buffer. */
static mf_result_t load_check(mf_job_t *job, const char *part)
{
    FILE *f = mode_store_stage_open("node.lua", "rb");
    if (f == NULL) return MF_STORAGE;
    size_t len = fread(job->scratch, 1, job->scratch_cap - 1, f);
    bool more = fgetc(f) != EOF;
    fclose(f);
    if (more) return MF_LOAD; /* larger than the preset buffer */
    job->scratch[len] = '\0';

    int parts = part_count(job->join->mode_id);
    size_t total = len + (parts > 1 ? 8u * (size_t)parts : 0u);
    char id[MP_ID_MAX + 1];
    for (int i = 0; part_at(job->join->mode_id, i, id); i++) {
        long other = strcmp(id, part) == 0 ? 0 : mode_store_source_len(id);
        if (other > 0) total += (size_t)other;
    }
    if (total >= PRESET_SOURCE_MAX) return MF_LOAD;

    atalaia_node_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.node_id = job->join->node_id;
    cfg.game_seed = job->join->game_seed;
    cfg.mem_limit = job->mem_limit;
    cfg.instr_limit = 1000000;
    atalaia_node_t *node = atalaia_node_create(&cfg);
    if (node == NULL) return MF_LOAD;
    const char *teams[ATALAIA_JOIN_TEAMS_MAX];
    for (uint8_t t = 0; t < job->join->team_count; t++) teams[t] = job->join->teams[t];
    bool ok = atalaia_node_set_teams(node, teams, job->join->team_count);
    if (ok && job->join->params_json[0]) atalaia_node_set_params(node, job->join->params_json);
    ok = ok && atalaia_node_load(node, job->scratch, len, "mode/node.lua") &&
         atalaia_node_status(node) == ATALAIA_NODE_RUNNING;
    atalaia_node_destroy(node);
    return ok ? MF_INSTALLED : MF_LOAD;
}

static mf_result_t fetch_part(mf_job_t *job, const fw_io_t *io, const char *part)
{
    memset(&job->release, 0, sizeof(job->release));
    job->key_id[0] = '\0';
    char text[MP_RELEASE_TEXT_MAX + 1];
    int len = 0;
    mf_result_t r = fetch_release(job, io, part, text, sizeof(text), &len);
    if (r == MF_INSTALLED) r = check_release(job, part, text, (size_t)len);
    /* Room: the least recently used package goes (never one of this game's parts). */
    if (r == MF_INSTALLED && !mode_store_make_room(job->release.size, part, job->join->mode_id)) {
        r = MF_NO_SPACE;
    }
    if (r != MF_INSTALLED) return r;
    if (!mode_store_stage_begin()) return MF_STORAGE;
    r = download(job, io, part);
    bool screens_bad = false;
    if (r == MF_INSTALLED) r = extract(job, &screens_bad);
    if (r == MF_INSTALLED && screens_bad) r = MF_LOAD;
    if (r == MF_INSTALLED) r = load_check(job, part);
    if (r == MF_INSTALLED) {
        ms_fetched_t meta;
        memset(&meta, 0, sizeof(meta));
        snprintf(meta.id, sizeof(meta.id), "%s", part);
        snprintf(meta.version, sizeof(meta.version), "%s", job->release.version);
        snprintf(meta.key_id, sizeof(meta.key_id), "%s", job->key_id);
        snprintf(meta.sha256, sizeof(meta.sha256), "%s", job->release.sha256_hex);
        meta.bytes = job->release.size;
        if (!mode_store_commit(&meta, text, (size_t)len)) r = MF_STORAGE;
    }
    if (r != MF_INSTALLED) mode_store_stage_abort();
    return r;
}

/* ---- the job ----------------------------------------------------------------------------- */

static void report(mf_job_t *job, const fw_io_t *io, const char *part, mf_result_t r)
{
    job->reported = false;
    if (job->base[0] == '\0' || io->post == NULL) return; /* no address answered */
    char *body = malloc(MF_REPORT_MAX);
    char mac[65];
    if (body != NULL &&
        mf_report(job->join, part, r, job->release.version, body, MF_REPORT_MAX, mac) > 0) {
        job->reported = io->post(io->ctx, job->base, MF_REPORT_PATH, body, mac);
    }
    free(body);
}

mf_result_t mf_run(mf_job_t *job, const fw_io_t *io)
{
    memset(&job->release, 0, sizeof(job->release));
    job->part[0] = '\0';
    job->base[0] = '\0';
    job->key_id[0] = '\0';
    job->installed = 0;
    job->reported = false;
    const atalaia_join_t *j = job->join;
    int missing = mf_missing(j);
    char id[MP_ID_MAX + 1];
    for (int i = 0; missing > 0 && part_at(j->mode_id, i, id); i++) {
        if (!mode_store_has(id)) {
            snprintf(job->part, sizeof(job->part), "%s", id); /* the first missing part */
            break;
        }
    }
    if (missing == 0) return MF_INSTALLED;
    if (missing < 0) return MF_BAD_RELEASE; /* not a mode id: nothing to ask for */
    if (job->key_count == 0) return MF_NO_KEY;
    if (!j->has_ca || j->url_count == 0) return MF_UNREACHABLE;
    if (job->buf == NULL || job->buf_cap < MP_BLOCK || job->scratch == NULL ||
        job->scratch_cap < MS_SCREEN_MAX + 1) {
        return MF_STORAGE;
    }
    if (io->cancelled(io->ctx)) return MF_CANCELLED;
    if (!io->net_up(io->ctx)) {
        io->net_down(io->ctx);
        return MF_NO_WIFI;
    }
    mf_result_t r = MF_INSTALLED;
    for (int i = 0; part_at(j->mode_id, i, id); i++) {
        if (mode_store_has(id)) continue; /* built in, or fetched before */
        snprintf(job->part, sizeof(job->part), "%s", id);
        r = fetch_part(job, io, id);
        report(job, io, id, r);
        if (r != MF_INSTALLED) break;
        job->installed++;
    }
    io->net_down(io->ctx);
    return r;
}
