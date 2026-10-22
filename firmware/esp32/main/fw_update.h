/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Firmware updates over the air (protocol/firmware-update.md, decisions FU3-*):
 * the Field Box's own checks, platform-free so the host tests run exactly
 * this code with fakes (test/test_fw_update.c); fw_update_esp.c supplies the
 * Wi-Fi, HTTPS and esp_ota_* operations.
 *
 *   CMD update {"id", "version"} (or "@update" on the console)
 *   -> refused while a game is played, without release keys, without the
 *      join's field CA and addresses (keys 13 and 14), for a version not
 *      above this one, on a low battery
 *   -> Wi-Fi up; GET <url>/api/v1/firmware/<id>/release over HTTPS pinned to
 *      the join's field CA
 *   -> the release text checked: its form, the Ed25519 signature over the
 *      manifest with a release key built into this firmware, the platform,
 *      the version (the offered one, above this one), the size (fits the
 *      slot), the SHA-256 (starts with the offered id)
 *   -> GET .../image streamed: its first bytes (ESP image header,
 *      esp_app_desc_t, the Atalaia descriptor) must declare the same version,
 *      this project, this variant and this board before anything is written;
 *      then into the inactive OTA slot, hashed as it goes
 *   -> size and SHA-256 equal to the signed ones, the image valid
 *      (esp_ota_end), only then the boot partition set; report; reboot.
 * Any failure aborts the slot's write: the running image is never touched.
 * After the reboot the new image checks itself (fw_update_self_test and the
 * shell's radio and storage) before it confirms; otherwise the bootloader
 * goes back to the previous image (CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE).
 */
#ifndef ATALAIA_FW_UPDATE_H
#define ATALAIA_FW_UPDATE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/join.h"

#define FW_MANIFEST_HEADER  "atalaia-firmware-release-v1"
#define FW_PLATFORM_MAX     15  /* "esp32s3" */
#define FW_VERSION_MAX      35  /* 4.4.4 digits, '-' and 20 characters */
#define FW_RELEASE_ID_LEN   16  /* hex digits: the start of the image's SHA-256 */
#define FW_KEYS_MAX         4   /* release keys a firmware carries (rotation) */
#define FW_RELEASE_TEXT_MAX 512 /* bytes of a release text (about 250 in practice) */
#define FW_IMAGE_HEAD       324 /* image header 24 + segment header 8 + app desc 256 + ours 36 */
#define FW_APP_DESC_OFFSET  32
#define FW_DESC_OFFSET      288
#define FW_PROJECT_NAME     "atalaia_esp32"
#define FW_REPORT_MAX       192

/* The Atalaia descriptor, right after esp_app_desc_t in the image (fw_desc.c). */
typedef struct {
    uint8_t magic[4]; /* "ATFW" */
    uint8_t format;   /* 1 */
    uint8_t reserved[3];
    char variant[12]; /* "box", "box-bench", "box-dev": an image installs only on its own variant */
    char board[16];   /* "heltec_v4_3", "heltec_v4_2" */
} fw_desc_t;

/* This image's own descriptor (fw_desc.c on the device; the tests define their own). */
extern const fw_desc_t atalaia_fw_desc;

typedef enum {
    FW_INSTALLED = 0,  /* the new image is set to boot: reboot */
    FW_BUSY,           /* a game is being played */
    FW_BAD_OFFER,      /* the command's params are not {"id", "version"} */
    FW_NO_KEY,         /* no release key in this firmware */
    FW_NO_LINK,        /* the join has no field CA or no address (keys 13 and 14) */
    FW_NO_WIFI,        /* no field Wi-Fi set, or it did not connect */
    FW_UNREACHABLE,    /* no address of the controller answered */
    FW_BAD_RELEASE,    /* the release text is malformed or is not the offered release */
    FW_BAD_SIGNATURE,  /* no release key of this firmware signed this manifest */
    FW_WRONG_PLATFORM, /* for another platform */
    FW_NOT_NEWER,      /* not above the running version (anti-rollback) */
    FW_TOO_BIG,        /* larger than the OTA slot */
    FW_BAD_IMAGE,      /* the image's descriptors are missing or say another version */
    FW_WRONG_BOARD,    /* built for another variant or board */
    FW_DOWNLOAD,       /* the download broke off, or sent more or less than the size */
    FW_BAD_HASH,       /* the bytes are not the signed image */
    FW_FLASH,          /* writing, validating or activating the slot failed */
    FW_BATTERY,        /* the battery is too low to start */
    FW_CANCELLED,      /* a game started during the download */
} fw_result_t;

/* The report's code for a result ("installed", "bad_signature", ...). */
const char *fw_result_name(fw_result_t r);

/* ---- versions ----------------------------------------------------------------------- */

/* MAJOR.MINOR.PATCH (1-4 digits each) with an optional pre-release (-[0-9A-Za-z][0-9A-Za-z.]{0,19},
 * no empty identifier), as firmware_release.py's VERSION. */
bool fw_version_valid(const char *v);
/* <0, 0, >0 as a sorts before, with or after b (Semantic Versioning 2.0.0 section 11); both
 * must be valid. */
int fw_version_compare(const char *a, const char *b);

/* ---- release texts and signatures ----------------------------------------------------- */

typedef struct {
    char platform[FW_PLATFORM_MAX + 1];
    char version[FW_VERSION_MAX + 1];
    uint32_t size;
    uint8_t sha256[32];
    char sha256_hex[65];
    uint8_t signature[64];
    size_t manifest_len; /* the signed bytes: the text's first five lines */
} fw_release_t;

/* Parses a release text (manifest + "signature=<base64>\n", exactly). false if malformed. */
bool fw_release_parse(const char *text, size_t len, fw_release_t *out);

/* True if one of keys signed the manifest (text's first manifest_len bytes) with Ed25519. */
bool fw_release_signed(const fw_release_t *rel, const char *text, const uint8_t (*keys)[32],
                       size_t key_count);

/* Release keys from the Kconfig string: 64 hex digits each, separated by spaces or commas.
 * Returns how many (0-FW_KEYS_MAX), or -1 if the text is malformed or holds too many. */
int fw_keys_parse(const char *text, uint8_t (*keys)[32], size_t cap);

/* The offer's params {"id": 16 hex, "version": ...} (a CMD's compact JSON). */
bool fw_offer_parse(const char *params_json, char id[FW_RELEASE_ID_LEN + 1],
                    char version[FW_VERSION_MAX + 1]);

/* ---- the image ------------------------------------------------------------------------ */

typedef struct {
    char version[33];
    char project[33];
    char variant[13];
    char board[17];
} fw_image_info_t;

/* What an image's first FW_IMAGE_HEAD bytes declare; false if they are not an Atalaia image. */
bool fw_image_info(const uint8_t *head, size_t len, fw_image_info_t *out);

/* ---- the job ---------------------------------------------------------------------------- */

typedef struct {
    int (*begin)(void *ctx, uint32_t size); /* 0 = ok: the inactive slot is ready (erased) */
    int (*write)(void *ctx, const uint8_t *data, size_t len);
    int (*end)(void *ctx);      /* 0 = the written image is valid (esp_ota_end) */
    int (*activate)(void *ctx); /* 0 = boot from it next (esp_ota_set_boot_partition) */
    void (*abort)(void *ctx);   /* forget the partial write (esp_ota_abort) */
} fw_flash_ops_t;

typedef struct {
    bool (*net_up)(void *ctx); /* join the field Wi-Fi; false: none set or it failed */
    void (*net_down)(void *ctx);
    /* GET base+path into buf (NUL-terminated); its length, or -1 (no answer, not 200, too big). */
    int (*get_text)(void *ctx, const char *base, const char *path, char *buf, size_t cap);
    /* GET base+path as a stream: true with the Content-Length (-1 if none). */
    bool (*open)(void *ctx, const char *base, const char *path, int64_t *length);
    int (*read)(void *ctx, uint8_t *buf, size_t cap); /* >0 bytes, 0 at the end, <0 an error */
    void (*close)(void *ctx);
    /* POST the report (text) with its MAC header: true if the controller answered 200 (it took
     * the report, accepted or not); false and the box tells it over LoRa (node.update_failed). */
    bool (*post)(void *ctx, const char *base, const char *path, const char *body,
                 const char *mac_hex);
    bool (*cancelled)(void *ctx); /* a game started: stop at once */
    void (*progress)(void *ctx, uint32_t done, uint32_t total);
    fw_flash_ops_t flash;
    void *ctx;
} fw_io_t;

typedef struct {
    /* The offer. */
    char id[FW_RELEASE_ID_LEN + 1];
    char version[FW_VERSION_MAX + 1];
    /* This box. */
    const char *platform;        /* "esp32s3" */
    const char *running_version; /* this image's version */
    const fw_desc_t *desc;       /* this image's descriptor (variant, board) */
    const uint8_t (*keys)[32];
    size_t key_count;
    uint32_t slot_size; /* bytes of the inactive OTA slot */
    bool playing;       /* a game is being played (BOX_PLAYING) */
    int battery_pct;    /* -1 if unknown */
    int min_battery_pct;
    /* The joined game: the controller's addresses, the field CA (the I/O pins it), and what
     * the report needs. */
    const atalaia_join_t *join;
    /* Out. */
    fw_release_t release;
    uint32_t written;
    char base[ATALAIA_JOIN_URL_MAX + 1]; /* the address that answered */
    bool reported; /* the controller took the HTTPS report; false: tell it over LoRa */
} fw_job_t;

/*
 * The checks that need no network: game, keys, link, version, battery. FW_INSTALLED means
 * "go on"; the shell shows the refusal at once.
 */
fw_result_t fw_update_precheck(const fw_job_t *job);

/*
 * The whole update: precheck, network, release, image, activation, report. Returns
 * FW_INSTALLED when the new image boots next (the caller reboots), or why it stopped; the
 * running image is untouched whatever happens before FW_INSTALLED.
 */
fw_result_t fw_update_run(fw_job_t *job, const fw_io_t *io);

/* The report a box posts (protocol/firmware-update.md) and its HMAC-SHA256 with the game key. */
size_t fw_report(const atalaia_join_t *join, const char *id, fw_result_t result,
                 const char *version, char *body, size_t cap, char mac_hex[65]);

/*
 * After an update, before the new image confirms itself: SHA-256 and Ed25519 known-answer
 * checks (RFC 8032 TEST 1), the release keys parse, a join round trip, and a Lua node runs a
 * script. False: something the next update needs is broken (roll back).
 */
bool fw_update_self_test(const uint8_t (*keys)[32], size_t key_count);

#endif /* ATALAIA_FW_UPDATE_H */
