/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Fetched mode packages on the box's storage (phase 5 plan phase 13b, decisions
 * P5B-12, P5B-15 and P5E-*). Platform-free over the C library's files and
 * folders: LittleFS on the ESP32 (esp_littlefs), a folder in the host tests.
 *
 *   <base>/modes/<id>/node.lua                the script (the preset store's path)
 *   <base>/modes/<id>/assets/screens/<n>.yaml its screen templates
 *   <base>/modes/<id>/release                 the signed release text it came with
 *   <base>/modes/<id>/fetched                 its slot: id, version, the key id that signed
 *                                             it, SHA-256, archive size, last use by a game
 *   <base>/modes/.new/                        a package being fetched (never a mode id)
 *   <base>/modes/.old/                        the version it replaces, while it does
 *
 * A package is kept only after every check: it is written into .new while it is
 * fetched and checked; the commit renames the older version (if any) to .old,
 * .new to <id>, then removes .old, and adds a preset for it. A box that loses
 * power on the way finishes or forgets the commit at its next start
 * (mode_store_init), so a failed or broken fetch leaves the box as it was.
 */
#ifndef ATALAIA_MODE_STORE_H
#define ATALAIA_MODE_STORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "builtin_screens.h"
#include "fw_update.h"
#include "mode_package.h"

#define MS_FETCHED_MAX   8              /* fetched packages a box keeps (P5B-12) */
#define MS_FETCHED_BYTES (512u * 1024u) /* bytes they keep in all */
#define MS_SCREEN_MAX    4096           /* bytes of a screen template (ATALAIA_TPL_SOURCE_MAX) */

typedef struct {
    char id[MP_ID_MAX + 1];
    char version[FW_VERSION_MAX + 1];
    char key_id[17];
    char sha256[65];
    uint32_t bytes; /* the archive's size (the limit counts archives, box_limits) */
    uint32_t used;  /* the last game that used it, as a count (the least recently used goes) */
} ms_fetched_t;

/* Where the store lives ("/littlefs"); finishes or forgets a commit a power loss cut short and
 * gives every fetched mode a preset. 0 = ok. */
int mode_store_init(const char *base_path);

/* At boot: each kept release's signature checked again with the keys of the firmware it now
 * runs (a key a release took out, a revocation, leaves its packages unused): a package whose
 * release does not verify, or is not the one its slot names, is dropped. Returns how many. */
int mode_store_verify(const uint8_t (*keys)[32], size_t key_count);

/* True if the mode's script is stored (a built-in mode's or a fetched one's). */
bool mode_store_has(const char *id);

/* The script's length, or -1 if it is not stored. */
long mode_store_source_len(const char *id);

/* True (and *out filled, when not NULL) if id is a fetched mode. */
bool mode_store_fetched(const char *id, ms_fetched_t *out);

/* The fetched modes (up to cap). */
int mode_store_list(ms_fetched_t *out, int cap);

/* ---- a package on its way ------------------------------------------------------------ */

/* An empty .new folder. */
bool mode_store_stage_begin(void);
/* A file in it ("package.tar", "node.lua", "assets/screens/<n>.yaml"), as fopen's mode. */
FILE *mode_store_stage_open(const char *name, const char *how);
bool mode_store_stage_remove(const char *name);
/* Forgets the package on its way. */
void mode_store_stage_abort(void);

/*
 * Room for a package of bytes: while the fetched modes would be more than MS_FETCHED_MAX or
 * MS_FETCHED_BYTES with it, the one a game used least recently goes, never replacing (the id
 * being replaced, counted as gone) nor a part of keep ("a+b+c", the joined game's mode). false
 * if there cannot be room.
 */
bool mode_store_make_room(uint32_t bytes, const char *replacing, const char *keep);

/* Keeps the package in .new as meta->id (replacing an older version), with its release text,
 * and gives it a preset. false: storage failed (the older version, if any, stays). */
bool mode_store_commit(const ms_fetched_t *meta, const char *release_text, size_t len);

/* Forgets a fetched mode (its folder and its presets). Never a built-in one: false. */
bool mode_store_remove(const char *id);

/* Forgets every fetched mode (join key 17, "@forgetmodes"). Returns how many. */
int mode_store_forget_all(void);

/* A game uses the mode ("a+b"): its fetched parts become the most recently used. */
void mode_store_touch(const char *mode_id);

/*
 * The screen template name of a fetched mode part (part, n bytes: one part of a "a+b" mode
 * id), read from storage into a buffer kept for the next call (the renderer parses it at once),
 * or NULL. For screen_template_set_fetched (screen_template.h).
 */
const builtin_screen_t *mode_store_screen(const char *part, size_t n, const char *name);

#endif /* ATALAIA_MODE_STORE_H */
