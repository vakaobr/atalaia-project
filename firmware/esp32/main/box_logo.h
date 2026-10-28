/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The field's logo on the Field Box's TFT (decision PKG-1; protocol/mode-packages.md, section 8).
 * The controller prepares the logo (a PNG, fitted into 96x96 pixels and written as RGB565), so the
 * box carries no image decoder: it fetches the 18,440 bytes over the same HTTPS the mode packages
 * use (never over LoRa), keeps them in its LittleFS under the source image's SHA-256, and draws
 * them as they are. Platform-free like mode_fetch.c, so the host tests run it with fakes
 * (test/test_box_logo.c); box_logo_esp.c supplies the task.
 *
 *   a joined game whose join names the controller (keys 13 and 14), the box not playing:
 *   -> Wi-Fi up; GET <url>/api/v1/field/box-logo/release over HTTPS pinned to the field CA
 *      "atalaia-box-logo-v1\nid=<64 hex>\nsha256=<64 hex>\nbytes=18440\n"
 *   -> the id is the kept one: nothing more (kept, the common case)
 *   -> else GET .../box-logo streamed into logo.new, hashed as it goes; the bytes must be the
 *      promised size and SHA-256 and a header of this format, then renamed over logo.bin
 *   -> a controller that answers 404 has no logo a box can draw (none, or not a PNG): the kept
 *      logo is removed and the box shows the Atalaia logo again.
 * A failure of any other kind leaves what the box kept as it was.
 */
#ifndef ATALAIA_BOX_LOGO_H
#define ATALAIA_BOX_LOGO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/join.h"
#include "fw_update.h"

#define BL_SIDE     96
#define BL_HEADER   8
#define BL_PIXELS   ((size_t)BL_SIDE * BL_SIDE)
#define BL_BYTES    (BL_HEADER + BL_PIXELS * 2) /* 18,440 */
#define BL_ID_LEN   64                          /* hex digits of the source image's SHA-256 */
#define BL_PATH     "/api/v1/field/box-logo"
#define BL_TEXT_MAX 192

typedef enum {
    BL_KEPT = 0,    /* the box has the controller's logo (fetched now, or already kept) */
    BL_NONE,        /* the controller has no logo a box can draw: none is kept now */
    BL_NO_WIFI,     /* no field Wi-Fi set, or it did not connect */
    BL_UNREACHABLE, /* no address of key 14 answered */
    BL_BAD,         /* a release that is not one, or bytes that are not as promised */
    BL_STORAGE,     /* writing to the flash failed */
    BL_CANCELLED,   /* a game started while the box was fetching */
} bl_result_t;

/* Where the logo lives ("/littlefs"). 0 = ok. */
int box_logo_init(const char *base_path);

/* The kept logo's source id (64 hex digits and a NUL), or false when none is kept. */
bool box_logo_kept(char id[BL_ID_LEN + 1]);

/* The kept logo's pixels, loaded into memory for the screen (BL_PIXELS RGB565 words, 96 rows of
 * 96, in the flash's order; the header is not in them), or NULL when none is kept or there is no
 * memory. box_logo_unload frees them: the renderer loads when a screen that shows the logo is
 * built and unloads when it is torn down. A new logo is drawn from the next build on. */
const uint16_t *box_logo_load(void);
void box_logo_unload(void);

/* Forgets the kept logo (a box taken to another field). */
void box_logo_forget(void);

/* The release text's three values; false if it is not a release of this format. */
bool box_logo_parse_release(const char *text, size_t len, char id[BL_ID_LEN + 1], char sha_hex[65],
                            uint32_t *bytes);

/* The path of the release text ("release") or of the bytes (NULL). */
void box_logo_path(char *buf, size_t cap, const char *what);

/* The whole fetch from the join's addresses, over io (get_text, open/read/close, net_up/down,
 * cancelled). buf: at least 512 bytes for the download (4 KiB is quicker). */
bl_result_t box_logo_run(const atalaia_join_t *join, const fw_io_t *io, uint8_t *buf,
                         size_t buf_cap);

const char *box_logo_result_name(bl_result_t r);

#endif /* ATALAIA_BOX_LOGO_H */
