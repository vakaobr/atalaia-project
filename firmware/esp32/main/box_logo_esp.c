/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Fetching the field's logo on the ESP32-S3 (box_logo_esp.h). The checks are box_logo.c's; this
 * file gives them the Wi-Fi and HTTPS of firmware updates and a task. Its memory (the join's copy,
 * the 4 KB buffer) lives on the heap only while the fetch runs.
 */
#include "box_logo_esp.h"

#include <stdlib.h>
#include <string.h>

#include "box_logo.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "fw_update_esp.h"

static const char *TAG = "box_logo";

#define LOGO_BUF   4096
#define LOGO_STACK 10240 /* TLS, as the mode fetch's */

typedef struct {
    atalaia_join_t join; /* a copy: the game task keeps its own */
    uint8_t *buf;
} job_t;

static box_game_t *s_box;
static volatile bool s_running;
static bool s_asked; /* this game has asked */
static uint32_t s_game_id;

static bool cancelled(void *ctx)
{
    (void)ctx;
    return s_box != NULL && (box_game_playing(s_box) || box_game_fetching(s_box));
}

static void logo_task(void *arg)
{
    job_t *job = arg;
    fw_io_t io = *fw_update_esp_net(job->join.ca_sha256);
    io.cancelled = cancelled;
    io.progress = NULL;
    io.ctx = NULL;
    bl_result_t r = box_logo_run(&job->join, &io, job->buf, LOGO_BUF);
    fw_update_esp_net_release();
    ESP_LOGI(TAG, "game %u: %s", (unsigned)job->join.game_id, box_logo_result_name(r));
    memset(&job->join, 0, sizeof(job->join));
    free(job->buf);
    free(job);
    s_running = false;
    vTaskDelete(NULL);
}

void box_logo_esp_init(box_game_t *box)
{
    s_box = box;
    if (box_logo_init("/littlefs") != 0) ESP_LOGW(TAG, "no storage for the field's logo");
}

bool box_logo_esp_pending(void)
{
    if (s_box == NULL) return false;
    if (s_running) return true;
    const atalaia_join_t *j = &s_box->join;
    return s_box->phase == BOX_JOINED && j->has_ca && j->url_count != 0 &&
           !(s_asked && s_game_id == j->game_id);
}

void box_logo_esp_poll(void)
{
    if (s_box == NULL || s_running || s_box->phase != BOX_JOINED) return;
    const atalaia_join_t *j = &s_box->join;
    if (!j->has_ca || j->url_count == 0) return;
    if (s_asked && s_game_id == j->game_id) return;
    s_asked = true;
    s_game_id = j->game_id;
    if (!fw_update_esp_net_claim()) return; /* a firmware update or a mode fetch has the Wi-Fi */
    job_t *job = calloc(1, sizeof(*job));
    bool started = false;
    if (job != NULL) {
        job->buf = malloc(LOGO_BUF);
        job->join = *j;
        memset(job->join.game_key, 0, sizeof(job->join.game_key)); /* the logo needs no key */
        if (job->buf != NULL) {
            s_running = true;
            started = xTaskCreatePinnedToCore(logo_task, "box_logo", LOGO_STACK, job, 1, NULL, 0) ==
                      pdPASS;
            if (!started) s_running = false;
        }
    }
    if (!started) {
        ESP_LOGW(TAG, "no memory for the logo's fetch");
        if (job != NULL) free(job->buf);
        free(job);
        fw_update_esp_net_release();
    }
}
