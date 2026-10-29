/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Field Box's iBeacon on NimBLE (see box_beacon_esp.h). Written for this project against the
 * NimBLE host API of ESP-IDF v5.3 (its headers and the programming guide); no example code is
 * copied.
 */
#include "box_beacon_esp.h"

#include "sdkconfig.h"

#if defined(CONFIG_ATALAIA_BOX_BEACON) && defined(CONFIG_BT_NIMBLE_ENABLED)

#include <string.h>

#include "esp_bt.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"

static const char *TAG = "box-beacon";

#define BEACON_TASK_STACK 4096

/* What the shell asked for (any task), and what the beacon's task has made true. */
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static bool want_on;
static box_beacon_id_t want_id;
static TaskHandle_t task;
static volatile bool up; /* the controller is advertising */

/* Owned by the beacon's task. */
static bool stack_up;
static box_beacon_id_t have_id;
static uint8_t adv[BOX_BEACON_ADV_SIZE];

static esp_power_level_t power_level(int dbm)
{
    /* ESP32-S3 levels: -24, -21, -18, -15, -12, -9, -6, -3, 0, 3, 6, 9, 12, 15, 18, 21 dBm. */
    static const int8_t dbms[] = {-24, -21, -18, -15, -12, -9, -6, -3, 0, 3, 6, 9, 12, 15, 18, 20};
    int best = 0, dist = 1000;
    for (int i = 0; i < (int)(sizeof(dbms) / sizeof(dbms[0])); i++) {
        int d = dbm > dbms[i] ? dbm - dbms[i] : dbms[i] - dbm;
        if (d < dist) {
            dist = d;
            best = i;
        }
    }
    return (esp_power_level_t)best;
}

static void advertise(void)
{
    uint8_t own;
    if (ble_hs_util_ensure_addr(0) != 0 || ble_hs_id_infer_auto(0, &own) != 0) {
        ESP_LOGE(TAG, "no Bluetooth address");
        return;
    }
    int rc = ble_gap_adv_set_data(adv, (int)sizeof(adv));
    if (rc != 0) {
        ESP_LOGE(TAG, "advertising data refused (%d)", rc);
        return;
    }
    struct ble_gap_adv_params p;
    memset(&p, 0, sizeof(p));
    p.conn_mode = BLE_GAP_CONN_MODE_NON; /* nobody connects to a beacon */
    p.disc_mode = BLE_GAP_DISC_MODE_GEN;
    p.itvl_min = p.itvl_max = box_beacon_interval_units(CONFIG_ATALAIA_BOX_BEACON_INTERVAL_MS);
    rc = ble_gap_adv_start(own, NULL, BLE_HS_FOREVER, &p, NULL, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "advertising failed (%d)", rc);
        return;
    }
    esp_err_t pw =
        esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, power_level(CONFIG_ATALAIA_BOX_BEACON_TX_DBM));
    if (pw != ESP_OK) ESP_LOGW(TAG, "transmit power not set (%s)", esp_err_to_name(pw));
    up = true;
    char text[37];
    box_beacon_uuid_text(have_id.uuid, text);
    ESP_LOGI(TAG, "advertising as iBeacon %s %u:%u every %d ms", text, (unsigned)have_id.major,
             (unsigned)have_id.minor, CONFIG_ATALAIA_BOX_BEACON_INTERVAL_MS);
}

static void on_sync(void)
{
    advertise();
}

static void on_reset(int reason)
{
    ESP_LOGW(TAG, "Bluetooth host reset (%d)", reason);
    up = false;
}

static void host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void stack_start(const box_beacon_id_t *id)
{
    have_id = *id;
    box_beacon_adv(id, (int8_t)CONFIG_ATALAIA_BOX_BEACON_MEASURED_POWER, adv);
    size_t before = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Bluetooth controller failed to start (%s): internal RAM %u bytes free",
                 esp_err_to_name(err), (unsigned)before);
        return;
    }
    /* The bench figure for the memory the controller takes (docs/runbooks/box-beacon-bench.md). */
    ESP_LOGI(TAG, "Bluetooth controller up: internal RAM %u bytes free (took %u)",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)(before - heap_caps_get_free_size(MALLOC_CAP_INTERNAL)));
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.reset_cb = on_reset;
    nimble_port_freertos_init(host_task);
    stack_up = true;
}

static void stack_stop(void)
{
    if (!stack_up) return;
    up = false;
    if (nimble_port_stop() != 0) ESP_LOGW(TAG, "Bluetooth host did not stop cleanly");
    nimble_port_deinit(); /* gives the controller's and the host's memory back */
    stack_up = false;
    ESP_LOGI(TAG, "iBeacon stopped");
}

static void beacon_task(void *arg)
{
    (void)arg;
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        bool on;
        box_beacon_id_t id;
        taskENTER_CRITICAL(&lock);
        on = want_on;
        id = want_id;
        taskEXIT_CRITICAL(&lock);
        bool same = stack_up && memcmp(&id, &have_id, sizeof(id)) == 0;
        if (on && same) continue;
        if (stack_up) stack_stop(); /* off, or another identity (a new game): start again */
        if (on) stack_start(&id);
    }
}

void box_beacon_esp_update(bool on, const box_beacon_id_t *id)
{
    bool changed;
    taskENTER_CRITICAL(&lock);
    changed = on != want_on || (on && memcmp(id, &want_id, sizeof(want_id)) != 0);
    want_on = on;
    if (on) want_id = *id;
    taskEXIT_CRITICAL(&lock);
    if (!changed) return;
    if (task == NULL) {
        if (!on) return;
        if (xTaskCreate(beacon_task, "beacon", BEACON_TASK_STACK, NULL, 3, &task) != pdPASS) {
            ESP_LOGE(TAG, "no task for the beacon");
            task = NULL;
            return;
        }
    }
    xTaskNotifyGive(task);
}

bool box_beacon_esp_running(void)
{
    return up;
}

#else /* no beacon in this build */

void box_beacon_esp_update(bool on, const box_beacon_id_t *id)
{
    (void)on;
    (void)id;
}

bool box_beacon_esp_running(void)
{
    return false;
}

#endif
