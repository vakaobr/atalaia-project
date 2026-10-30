/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Fetching mode packages on the ESP32-S3 (mode_fetch_esp.h). The checks are
 * mode_fetch.c's; this file gives them the mode keys, memory, the Wi-Fi and
 * HTTPS of firmware updates (pinned to the join's field CA) and a task, and
 * hands the result back to the game task. The job, its join and its buffers
 * live on the heap only while a fetch runs: no static RAM for a feature used
 * between games (the memory notes in sdkconfig.defaults).
 */
#include "mode_fetch_esp.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "box_text.h"
#include "builtin_presets.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "fw_update_esp.h"
#include "mode_fetch.h"
#include "mode_store.h"
#include "preset_store.h"
#include "sdkconfig.h"

static const char *TAG = "mode_fetch";

#define FETCH_BUF 4096
/* TLS, and a script's load in the sandbox, which runs its top level (decision SR-132: 20 C levels
 * of about 0.8 KB at the worst, the same chain as the game task's; no events run here, so 20 KB,
 * not 24). */
#define FETCH_STACK 20480

typedef struct {
    mf_job_t job;
    atalaia_join_t join; /* a copy: the game task keeps its own */
    mf_result_t result;
} fetch_t;

static box_game_t *s_box;
static void (*s_screen)(const char *tmpl, const char *data_json);
static bool s_reduced;
static size_t s_mem_limit;
/* The keys a box checks a mode package with (protocol/mode-packages.md, section 3): its mode keys,
 * then its release keys. */
static uint8_t s_keys[2 * FW_KEYS_MAX][32];
static int s_key_count = -1; /* mode keys */
static size_t s_all_keys;    /* mode keys and release keys */
static fetch_t *s_fetch;     /* while a fetch runs, until the game task has its result */
static volatile bool s_done;

size_t mode_fetch_esp_key_count(void)
{
    if (s_key_count < 0) {
        s_key_count = fw_keys_parse(CONFIG_ATALAIA_MODE_KEYS, s_keys, FW_KEYS_MAX);
        if (s_key_count < 0) {
            ESP_LOGE(TAG, "CONFIG_ATALAIA_MODE_KEYS is malformed: no mode package is accepted");
            s_key_count = 0;
        }
        int release =
            fw_keys_parse(CONFIG_ATALAIA_OTA_RELEASE_KEYS, s_keys + s_key_count, FW_KEYS_MAX);
        s_all_keys = (size_t)s_key_count + (release > 0 ? (size_t)release : 0u);
    }
    return (size_t)s_key_count;
}

static void show(const char *title, const char *text)
{
    char data[112];
    snprintf(data, sizeof(data), "{\"title\":\"%s\",\"mode\":\"%.40s\"}", title, text);
    if (s_screen != NULL) s_screen("status", data);
}

static bool cancelled(void *ctx)
{
    (void)ctx;
    return s_box != NULL && (s_box->fetch_cancel || box_game_playing(s_box));
}

static void progress(void *ctx, uint32_t done, uint32_t total)
{
    (void)ctx;
    static unsigned last = 101;
    unsigned pct = total ? (unsigned)((uint64_t)done * 100u / total) : 0;
    if (pct / 25 == last / 25 && last != 101 && pct != 100) return;
    last = pct;
    char text[80];
    snprintf(text, sizeof(text), "%.32s %u%%", s_fetch->job.release.id, pct);
    show(box_text(TX_MODES_FETCHING), text);
}

/* The fetch is over: its buffers go now, the rest once the game task has the result. */
static void finish(mf_result_t r)
{
    fetch_t *f = s_fetch;
    memset(f->join.game_key, 0, sizeof(f->join.game_key));
    free(f->job.buf);
    free(f->job.scratch);
    f->job.buf = NULL;
    f->job.scratch = NULL;
    f->result = r;
    __atomic_store_n(&s_done, true, __ATOMIC_RELEASE);
}

static void fetch_task(void *arg)
{
    (void)arg;
    fetch_t *f = s_fetch;
    fw_io_t io = *fw_update_esp_net(f->join.ca_sha256);
    io.cancelled = cancelled;
    io.progress = progress;
    io.ctx = NULL;
    mf_result_t r = mf_run(&f->job, &io);
    fw_update_esp_net_release();
    if (r == MF_INSTALLED) {
        ESP_LOGW(TAG, "%s: every part is on the box (%d fetched)", f->join.mode_id,
                 f->job.installed);
    } else {
        ESP_LOGW(TAG, "%s: %s (%s); %s", f->join.mode_id, mf_result_name(r), f->job.part,
                 f->job.reported ? "reported" : "not reported over HTTPS");
    }
    finish(r);
    vTaskDelete(NULL);
}

void mode_fetch_esp_init(box_game_t *box, void (*screen)(const char *tmpl, const char *data_json),
                         bool reduced, size_t mem_limit)
{
    s_box = box;
    s_screen = screen;
    s_reduced = reduced;
    s_mem_limit = mem_limit;
    size_t keys = mode_fetch_esp_key_count();
    if (keys == 0) {
        ESP_LOGI(TAG, "no mode key built in (CONFIG_ATALAIA_MODE_KEYS): a join that asks to fetch "
                      "a missing mode is answered no_mode");
    } else {
        ESP_LOGI(TAG, "%u mode key(s), %u with the release keys", (unsigned)keys,
                 (unsigned)s_all_keys);
    }
    /* The kept packages' releases again, with the keys of this firmware: a key a release took
     * out leaves its packages unused (protocol/mode-packages.md, section 5). */
    int dropped = mode_store_verify((const uint8_t(*)[32])s_keys, s_all_keys);
    if (dropped > 0) ESP_LOGW(TAG, "%d kept mode package(s) no longer verify: dropped", dropped);
}

void mode_fetch_esp_start(const atalaia_join_t *join)
{
    if (s_box == NULL) return;
    if (s_fetch != NULL) {
        ESP_LOGW(TAG, "a fetch is already running"); /* box_game never asks twice */
        return;
    }
    s_fetch = calloc(1, sizeof(*s_fetch));
    if (s_fetch == NULL) {
        /* No memory even for the job: the game task hears it as a fetch that found no room. */
        ESP_LOGE(TAG, "no memory for a fetch");
        __atomic_store_n(&s_done, true, __ATOMIC_RELEASE);
        return;
    }
    fetch_t *f = s_fetch;
    f->join = *join;
    mode_fetch_esp_key_count();
    f->job.keys = (const uint8_t(*)[32])s_keys;
    f->job.key_count = s_key_count > 0 ? s_all_keys : 0; /* no mode key: no_key */
    f->job.reduced = s_reduced;
    f->job.mem_limit = s_mem_limit;
    f->job.builtin = builtin_presets_has;
    f->job.join = &f->join;
    mf_result_t r = box_game_playing(s_box) ? MF_CANCELLED : MF_INSTALLED;
    bool net = false;
    if (r == MF_INSTALLED) {
        net = fw_update_esp_net_claim();
        if (!net) r = MF_NO_WIFI; /* a firmware update has the Wi-Fi (decision P5E-10) */
    }
    if (r == MF_INSTALLED) {
        /* Above 4 KB: PSRAM on a Full box (CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL); a Reduced box's
         * internal RAM is free between games (no Lua heap then). */
        f->job.buf = malloc(FETCH_BUF);
        f->job.buf_cap = FETCH_BUF;
        f->job.scratch = malloc(PRESET_SOURCE_MAX);
        f->job.scratch_cap = PRESET_SOURCE_MAX;
        if (f->job.buf == NULL || f->job.scratch == NULL) r = MF_STORAGE; /* no memory */
    }
    if (r == MF_INSTALLED && xTaskCreatePinnedToCore(fetch_task, "mode_fetch", FETCH_STACK, NULL, 2,
                                                     NULL, 0) != pdPASS) {
        ESP_LOGE(TAG, "no memory for the fetch task");
        r = MF_STORAGE;
    }
    if (r != MF_INSTALLED) {
        /* Refused before any network: the game task hears it at its next poll. */
        if (net) fw_update_esp_net_release();
        ESP_LOGW(TAG, "%s: %s", join->mode_id, mf_result_name(r));
        finish(r);
    }
}

void mode_fetch_esp_poll(void)
{
    if (s_box == NULL || !__atomic_load_n(&s_done, __ATOMIC_ACQUIRE)) return;
    __atomic_store_n(&s_done, false, __ATOMIC_RELEASE);
    fetch_t *f = s_fetch;
    if (f == NULL) {
        box_game_fetch_done(s_box, (int)MF_STORAGE, s_box->join.mode_id, false);
        return;
    }
    char part[MP_ID_MAX + 1];
    snprintf(part, sizeof(part), "%s", f->job.part[0] ? f->job.part : f->join.mode_id);
    bool reported = f->job.reported;
    mf_result_t r = f->result;
    memset(&f->join, 0, sizeof(f->join));
    s_fetch = NULL;
    free(f);
    box_game_fetch_done(s_box, (int)r, part, reported);
}
