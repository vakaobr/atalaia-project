/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A Field Box fetching the signed mode packages a game needs and it lacks
 * (phase 5 plan phase 13b; the contract is protocol/mode-packages.md, "Fetching
 * missing modes"; decisions P5B-11 to P5B-16, P5D-* and P5E-*). Platform-free
 * like fw_update.c, so the host tests run this code with fakes
 * (test/test_mode_fetch.c); mode_fetch_esp.c supplies the task, and
 * fw_update_esp.c the Wi-Fi and HTTPS pinned to the join's field CA.
 *
 *   a join with key 16 whose mode the box lacks (keys 13 and 14, a mode key)
 *   -> Wi-Fi up; for each missing part of the mode id, in order:
 *      GET <url>/api/v1/mode-packages/<id>/release over HTTPS pinned to the CA
 *   -> the release (the Python reference: box_check_release): no_key,
 *      bad_release (its exact lines, the id asked for), bad_signature (a mode
 *      key, then a release key, of this firmware), kind (no scenario), tier (a
 *      Reduced box takes no min_tier=full), builtin, too_big (256 KiB), then
 *      no_space (room made by dropping the least recently used package)
 *   -> GET .../package streamed into a file in .new, hashed as it goes
 *      (download, bad_hash: box_check_archive)
 *   -> the archive read back: its canonical form under the id with a node.lua
 *      (bad_archive); node.lua and assets/screens/<name>.yaml kept in .new, the
 *      rest not; mode.yaml is never read (the signed manifest says it all)
 *   -> node.lua loads in a fresh sandbox with this box's Lua heap (no game
 *      started), its screens parse, the composed game fits the 16 KB preset
 *      buffer (load)
 *   -> kept (mode_store_commit; a flash error: storage), the report posted.
 * The first failure stops the fetch: nothing of that part is kept, the parts
 * installed before it stay, and it is reported.
 */
#ifndef ATALAIA_MODE_FETCH_H
#define ATALAIA_MODE_FETCH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/join.h"
#include "fw_update.h"
#include "mode_package.h"

#define MF_PARTS_MAX   8    /* parts of a game's mode id ("main+modifier+...") */
#define MF_REPORT_MAX  1024 /* bytes of a report */
#define MF_REPORT_PATH "/api/v1/mode-packages/report"

/* The report's results, in protocol/mode-packages.md's order (BOX_RESULTS in the Python). */
typedef enum {
    MF_INSTALLED = 0, /* the part is in (for the whole run: every missing part is) */
    MF_NO_WIFI,       /* no field Wi-Fi set, or it did not connect */
    MF_UNREACHABLE,   /* no address of key 14 answered */
    MF_NOT_OFFERED,   /* the controller answered, but not 200 (404, 409: it does not offer it) */
    MF_DOWNLOAD,      /* a Content-Length other than the size, more bytes, a broken connection */
    MF_NO_KEY,        /* no mode key built into this firmware */
    MF_BAD_RELEASE,   /* not a release text, or another part's */
    MF_BAD_SIGNATURE, /* no key of this firmware signed this manifest */
    MF_KIND,          /* a scenario: it runs on the controller only */
    MF_TIER,          /* min_tier=full on a Reduced box */
    MF_BUILTIN,       /* a built-in mode's id: the firmware owns those */
    MF_TOO_BIG,       /* over 256 KiB */
    MF_BAD_HASH,      /* the bytes are not the signed archive */
    MF_BAD_ARCHIVE,   /* not the canonical archive under the id, or no node.lua */
    MF_LOAD,          /* the script does not load, a screen does not parse, the game does not fit */
    MF_NO_SPACE,      /* no room among the fetched packages */
    MF_STORAGE,       /* writing to the flash failed */
    MF_CANCELLED,     /* a game started (or the fetched one ended) while the box was fetching */
} mf_result_t;

/* The report's code for a result ("installed", "bad_signature", ...). */
const char *mf_result_name(mf_result_t r);

/* The path of a part's release text ("release") or archive ("package") on the controller. */
void mf_path(char *buf, size_t cap, const char *id, const char *what);

/* The report of one part (report_body in the Python): version NULL or "" when the box read no
 * release; kept: every package it keeps now (read from mode_store). And its HMAC-SHA256 with the
 * game key, lower-case hex. Returns the body's length, 0 if it does not fit. */
size_t mf_report(const atalaia_join_t *join, const char *part, mf_result_t result,
                 const char *version, char *body, size_t cap, char mac_hex[65]);

/* ---- the job ------------------------------------------------------------------------- */

typedef struct {
    /* This box. */
    const uint8_t (*keys)[32]; /* CONFIG_ATALAIA_MODE_KEYS, then the release keys */
    size_t key_count;
    bool reduced;                    /* a Reduced box (no PSRAM): refuses min_tier=full */
    size_t mem_limit;                /* its Lua heap: the load check's */
    bool (*builtin)(const char *id); /* a built-in mode's id (never fetched); NULL: none */
    /* The join: the mode id, the controller's addresses, the field CA (the I/O pins it), the
     * teams and parameters of the load check, the game key of the reports. */
    const atalaia_join_t *join;
    /* Memory the job uses: buf for the download and the archive's reading (at least 512 bytes;
     * 4 KiB is quicker), scratch for a script or a screen (PRESET_SOURCE_MAX). */
    uint8_t *buf;
    size_t buf_cap;
    char *scratch;
    size_t scratch_cap;
    /* Out. */
    char part[MP_ID_MAX + 1];            /* the part the result is about */
    mp_release_t release;                /* its release, when one was read (version "" otherwise) */
    char key_id[17];                     /* who signed it */
    char base[ATALAIA_JOIN_URL_MAX + 1]; /* the address that answered */
    int installed;                       /* parts fetched and kept by this run */
    bool reported;                       /* the controller took the last report (200) */
} mf_job_t;

/* Whether a join makes a box with key_count mode keys fetch (protocol/mode-packages.md, section
 * 1): key 16, keys 13 and 14, at least one key, and parts it lacks (mf_missing). */
bool mf_join_can_fetch(const atalaia_join_t *j, size_t key_count);

/* The parts of the join's mode id the box lacks: their number (0: none; -1: a part is not a
 * mode id or there are more than MF_PARTS_MAX). */
int mf_missing(const atalaia_join_t *j);

/*
 * The whole fetch: each missing part in order, its checks, its report. MF_INSTALLED when every
 * part the game needs is on the box (the caller then joins the game), or why it stopped
 * (job->part says which part, job->reported whether the controller heard it).
 */
mf_result_t mf_run(mf_job_t *job, const fw_io_t *io);

#endif /* ATALAIA_MODE_FETCH_H */
