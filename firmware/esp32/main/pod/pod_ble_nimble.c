/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's GATT service on NimBLE (see pod_ble_nimble.h). Written for
 * this project against the NimBLE host API of ESP-IDF v5.3 (its headers and
 * the ESP-IDF programming guide); no example code is copied.
 */
#include "pod_ble_nimble.h"

#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

/* NimBLE's NVS-backed store of bonds (ESP-IDF, CONFIG_BT_NIMBLE_NVS_PERSIST). */
void ble_store_config_init(void);

static const char *TAG = "pod-ble";

/* ---- Events from the host task to the pod task ---------------------------------- */

typedef enum {
    EV_CONNECT,
    EV_DISCONNECT,
    EV_ENCRYPTION,
    EV_SUBSCRIBE,
    EV_MTU,
    EV_WRITE,
} ev_kind_t;

typedef struct {
    uint8_t kind;
    uint8_t chr; /* EV_SUBSCRIBE: pod_ble_chr_t */
    bool flag;   /* EV_ENCRYPTION: encrypted; EV_SUBSCRIBE: notify */
    uint16_t conn;
    uint16_t value; /* EV_MTU */
    uint16_t len;   /* EV_WRITE */
    uint8_t data[POD_BLE_MTU_WANTED];
} ev_t;

#define EV_QUEUE_LEN 16

static QueueHandle_t events;
static uint16_t tx_handle, status_handle;
static uint8_t own_addr_type;
static bool want_encryption;
static char name[POD_BLE_NAME_SIZE];
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t status_copy[3] = {0xFF, 0x80, 0x00};

static void post(const ev_t *e)
{
    if (events == NULL || xQueueSend(events, e, 0) != pdTRUE) {
        ESP_LOGW(TAG, "event queue full: event %d dropped", e->kind);
    }
}

/* ---- GATT ------------------------------------------------------------------------ */

static ble_uuid128_t uuid_service, uuid_tx, uuid_rx, uuid_status;

static int chr_access(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)attr;
    (void)arg;
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        ev_t e = {.kind = EV_WRITE, .conn = conn};
        uint16_t len = 0;
        if (ble_hs_mbuf_to_flat(ctxt->om, e.data, sizeof(e.data), &len) != 0) {
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        }
        e.len = len;
        post(&e);
        return 0;
    }
    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
        uint8_t s[3];
        taskENTER_CRITICAL(&status_lock);
        memcpy(s, status_copy, sizeof(s));
        taskEXIT_CRITICAL(&status_lock);
        return os_mbuf_append(ctxt->om, s, sizeof(s)) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static struct ble_gatt_chr_def chrs[] = {
    {.uuid = &uuid_tx.u,
     .access_cb = chr_access,
     .flags = BLE_GATT_CHR_F_NOTIFY,
     .val_handle = &tx_handle},
    {.uuid = &uuid_rx.u, .access_cb = chr_access, .flags = BLE_GATT_CHR_F_WRITE_NO_RSP},
    {.uuid = &uuid_status.u,
     .access_cb = chr_access,
     .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
     .val_handle = &status_handle},
    {0},
};

static const struct ble_gatt_svc_def services[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY, .uuid = &uuid_service.u, .characteristics = chrs},
    {0},
};

static void uuid_from(ble_uuid128_t *u, const uint8_t le[16])
{
    u->u.type = BLE_UUID_TYPE_128;
    memcpy(u->value, le, 16);
}

/* ---- GAP ------------------------------------------------------------------------- */

static int gap_event(struct ble_gap_event *event, void *arg);

static void advertise(void)
{
    struct ble_gap_adv_params p;
    memset(&p, 0, sizeof(p));
    p.conn_mode = BLE_GAP_CONN_MODE_UND;
    p.disc_mode = BLE_GAP_DISC_MODE_GEN;
    int rc = ble_gap_adv_start(own_addr_type, NULL, BLE_HS_FOREVER, &p, gap_event, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) ESP_LOGE(TAG, "advertising failed (%d)", rc);
}

static int gap_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    ev_t e;
    memset(&e, 0, sizeof(e));
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status != 0) {
            advertise();
            return 0;
        }
        e.kind = EV_CONNECT;
        e.conn = event->connect.conn_handle;
        post(&e);
        /* Ask the phone to pair (or to encrypt with its bond): frames wait for it. */
        if (want_encryption) ble_gap_security_initiate(event->connect.conn_handle);
        return 0;
    case BLE_GAP_EVENT_DISCONNECT:
        e.kind = EV_DISCONNECT;
        post(&e);
        advertise();
        return 0;
    case BLE_GAP_EVENT_ENC_CHANGE:
        e.kind = EV_ENCRYPTION;
        e.conn = event->enc_change.conn_handle;
        e.flag = event->enc_change.status == 0;
        post(&e);
        return 0;
    case BLE_GAP_EVENT_SUBSCRIBE:
        if (event->subscribe.attr_handle != tx_handle &&
            event->subscribe.attr_handle != status_handle) {
            return 0;
        }
        e.kind = EV_SUBSCRIBE;
        e.conn = event->subscribe.conn_handle;
        e.chr = event->subscribe.attr_handle == tx_handle ? POD_BLE_TX : POD_BLE_STATUS;
        e.flag = event->subscribe.cur_notify != 0;
        post(&e);
        return 0;
    case BLE_GAP_EVENT_MTU:
        e.kind = EV_MTU;
        e.conn = event->mtu.conn_handle;
        e.value = event->mtu.value;
        post(&e);
        return 0;
    case BLE_GAP_EVENT_REPEAT_PAIRING: {
        /* A phone that lost its bond pairs again: forget the old one. */
        struct ble_gap_conn_desc desc;
        if (ble_gap_conn_find(event->repeat_pairing.conn_handle, &desc) == 0) {
            ble_store_util_delete_peer(&desc.peer_id_addr);
        }
        return BLE_GAP_REPEAT_PAIRING_RETRY;
    }
    case BLE_GAP_EVENT_ADV_COMPLETE: advertise(); return 0;
    default: return 0;
    }
}

static void on_sync(void)
{
    if (ble_hs_util_ensure_addr(0) != 0 || ble_hs_id_infer_auto(0, &own_addr_type) != 0) {
        ESP_LOGE(TAG, "no Bluetooth address");
        return;
    }
    uint8_t addr[6] = {0};
    ble_hs_id_copy_addr(own_addr_type, addr, NULL);
    pod_ble_device_name(addr, name);
    ble_svc_gap_device_name_set(name);

    uint8_t data[31];
    size_t n = pod_ble_adv_data(data, sizeof(data));
    int rc = ble_gap_adv_set_data(data, (int)n);
    n = pod_ble_scan_response(name, data, sizeof(data));
    if (rc == 0) rc = ble_gap_adv_rsp_set_data(data, (int)n);
    if (rc != 0) {
        ESP_LOGE(TAG, "advertising data refused (%d)", rc);
        return;
    }
    advertise();
    ESP_LOGI(TAG, "advertising as %s", name);
}

static void on_reset(int reason)
{
    ESP_LOGW(TAG, "Bluetooth host reset (%d)", reason);
}

static void host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

/* ---- Notifications --------------------------------------------------------------- */

static int notify(void *ctx, uint16_t conn, pod_ble_chr_t chr, const uint8_t *data, size_t len)
{
    (void)ctx;
    struct os_mbuf *om = ble_hs_mbuf_from_flat(data, (uint16_t)len);
    if (om == NULL) return 1; /* no buffer free: busy */
    /* ble_gatts_notify_custom() takes the buffer in every case. */
    int rc = ble_gatts_notify_custom(conn, chr == POD_BLE_TX ? tx_handle : status_handle, om);
    if (rc == 0) return 0;
    return rc == BLE_HS_ENOMEM || rc == BLE_HS_EBUSY ? 1 : -1;
}

const pod_ble_stack_t pod_ble_nimble_stack = {.notify = notify, .ctx = NULL};

/* ---- Start and poll -------------------------------------------------------------- */

bool pod_ble_nimble_start(bool encrypted)
{
    want_encryption = encrypted;
    events = xQueueCreate(EV_QUEUE_LEN, sizeof(ev_t));
    if (events == NULL) return false;
    uuid_from(&uuid_service, pod_ble_uuid_service);
    uuid_from(&uuid_tx, pod_ble_uuid_tx);
    uuid_from(&uuid_rx, pod_ble_uuid_rx);
    uuid_from(&uuid_status, pod_ble_uuid_status);
    if (encrypted) chrs[1].flags |= BLE_GATT_CHR_F_WRITE_ENC;

    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Bluetooth controller failed to start (%s)", esp_err_to_name(err));
        return false;
    }
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.reset_cb = on_reset;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    /* LE Secure Connections, Just Works (the pod has no display), bonded. */
    ble_hs_cfg.sm_io_cap = BLE_SM_IO_CAP_NO_IO;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = 0;
    ble_hs_cfg.sm_sc = 1;
    ble_hs_cfg.sm_our_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;
    ble_hs_cfg.sm_their_key_dist = BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID;

    ble_svc_gap_init();
    ble_svc_gatt_init();
    int rc = ble_gatts_count_cfg(services);
    if (rc == 0) rc = ble_gatts_add_svcs(services);
    if (rc != 0) {
        ESP_LOGE(TAG, "GATT service refused (%d)", rc);
        return false;
    }
    ble_store_config_init();
    nimble_port_freertos_init(host_task);
    return true;
}

void pod_ble_nimble_poll(pod_ble_t *b)
{
    ev_t e;
    while (events != NULL && xQueueReceive(events, &e, 0) == pdTRUE) {
        switch (e.kind) {
        case EV_CONNECT: pod_ble_on_connect(b, e.conn); break;
        case EV_DISCONNECT: pod_ble_on_disconnect(b); break;
        case EV_ENCRYPTION: pod_ble_on_encryption(b, e.flag); break;
        case EV_SUBSCRIBE: pod_ble_on_subscribe(b, (pod_ble_chr_t)e.chr, e.flag); break;
        case EV_MTU: pod_ble_on_mtu(b, e.value); break;
        case EV_WRITE: pod_ble_on_write(b, e.data, e.len); break;
        default: break;
        }
    }
}

void pod_ble_nimble_set_status(const uint8_t status[3])
{
    taskENTER_CRITICAL(&status_lock);
    memcpy(status_copy, status, sizeof(status_copy));
    taskEXIT_CRITICAL(&status_lock);
}
