/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's GATT service on NimBLE (see pod_ble_nimble.h). Written for
 * this project against the NimBLE host API of ESP-IDF v5.3 (its headers and
 * the ESP-IDF programming guide); no example code is copied.
 *
 * Pairing (decisions PODPK-1 to PODPK-11): LE Secure Connections, passkey
 * entry, bonded. The pod is DisplayOnly: NimBLE asks it to show a passkey
 * (BLE_SM_IOACT_DISP), the pod draws one at random, gives it to the stack and
 * to the OLED (pod_display.c) and the log, and the phone types it. pod_pair.c
 * decides on the pod task what the OLED shows and when a link goes; the
 * actions (drop a link, forget a bond, clear them all) are carried out here.
 */
#include "pod_ble_nimble.h"

#include <string.h>

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "pod_config.h"
#include "pod_pair.h"
#if CONFIG_ATALAIA_OLED_STATUS
#include "pod_display.h"
#endif

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
    EV_PASSKEY,
} ev_kind_t;

typedef struct {
    uint8_t kind;
    uint8_t chr;        /* EV_SUBSCRIBE: pod_ble_chr_t; EV_ENCRYPTION: pod_pair_result_t */
    bool flag;          /* EV_ENCRYPTION: encrypted; EV_SUBSCRIBE: notify */
    bool authenticated; /* EV_ENCRYPTION: the key is MITM-protected */
    uint16_t conn;
    uint16_t value;   /* EV_MTU */
    uint16_t len;     /* EV_WRITE */
    uint32_t passkey; /* EV_PASSKEY */
    uint8_t data[POD_BLE_MTU_WANTED];
} ev_t;

#define EV_QUEUE_LEN 16

static QueueHandle_t events;
static uint16_t tx_handle, status_handle;
static uint8_t own_addr_type;
static bool want_encryption;
static bool want_passkey;
static char name[POD_BLE_NAME_SIZE];
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t status_copy[3] = {0xFF, 0x80, 0x00};

/* The pairing: driven on the pod task (pod_ble_nimble_poll); the OLED task reads a copy. */
static pod_pair_t pair;
static uint16_t pair_conn;
static portMUX_TYPE view_lock = portMUX_INITIALIZER_UNLOCKED;
static oled_pair_view_t view_copy;

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static uint32_t random_word(void *ctx)
{
    (void)ctx;
    return esp_random(); /* the RF subsystem is on: true random numbers */
}

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
    case BLE_GAP_EVENT_ENC_CHANGE: {
        struct ble_gap_conn_desc desc;
        e.kind = EV_ENCRYPTION;
        e.conn = event->enc_change.conn_handle;
        int status = event->enc_change.status;
        if (status == 0 && ble_gap_conn_find(e.conn, &desc) == 0) {
            e.flag = desc.sec_state.encrypted;
            e.authenticated = desc.sec_state.authenticated;
        }
        /* BLE_HS_ENOENT: the phone asked to encrypt with a bond the pod does not have. */
        e.chr = status == 0                 ? POD_PAIR_RESULT_OK
                : status == BLE_HS_ETIMEOUT ? POD_PAIR_RESULT_TIMEOUT
                : status == BLE_HS_ENOENT   ? POD_PAIR_RESULT_NO_KEY
                                            : POD_PAIR_RESULT_FAILED;
        if (status != 0) ESP_LOGW(TAG, "pairing or encryption failed (%d)", status);
        post(&e);
        return 0;
    }
    case BLE_GAP_EVENT_PASSKEY_ACTION: {
        if (event->passkey.params.action != BLE_SM_IOACT_DISP) {
            /* DisplayOnly: the stack asks for nothing else. */
            ESP_LOGW(TAG, "pairing action %d not supported", event->passkey.params.action);
            return 0;
        }
        struct ble_sm_io io;
        memset(&io, 0, sizeof(io));
        io.action = BLE_SM_IOACT_DISP;
        io.passkey = pod_pair_passkey(random_word, NULL);
        int rc = ble_sm_inject_io(event->passkey.conn_handle, &io);
        if (rc != 0) {
            ESP_LOGE(TAG, "passkey refused by the stack (%d)", rc);
            return 0;
        }
        /* In the log too: a pod whose OLED is broken can still be paired on the bench. */
        ESP_LOGI(TAG, "pairing passkey %06lu", (unsigned long)io.passkey);
        e.kind = EV_PASSKEY;
        e.conn = event->passkey.conn_handle;
        e.passkey = io.passkey;
        post(&e);
        return 0;
    }
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
        /* A phone that lost its bond, or that pairs again because the pod asked for a passkey
         * and its bond has none (PODPK-4), pairs again: forget the old one. */
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
    pod_pair_set_name(&pair, name);

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

/* ---- Pairing: what the OLED shows, and the actions ------------------------------- */

static void read_view(oled_pair_view_t *out)
{
    taskENTER_CRITICAL(&view_lock);
    *out = view_copy;
    taskEXIT_CRITICAL(&view_lock);
}

static bool clear_button_down(void)
{
#if POD_BOND_CLEAR_PIN >= 0
    return gpio_get_level(POD_BOND_CLEAR_PIN) == 0;
#else
    return false;
#endif
}

static void clear_button_start(void)
{
#if POD_BOND_CLEAR_PIN >= 0
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << POD_BOND_CLEAR_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
#endif
}

static void act(pod_ble_t *b, pod_pair_action_t a)
{
    struct ble_gap_conn_desc desc;
    switch (a) {
    case POD_PAIR_ACT_DROP:
        ESP_LOGW(TAG, "pairing failed, or none within %d s: link dropped",
                 POD_PAIR_TIMEOUT_MS / 1000);
        ble_gap_terminate(pair_conn, BLE_ERR_REM_USER_CONN_TERM);
        break;
    case POD_PAIR_ACT_DROP_STALE:
        /* The pod's side of the bond goes; Authentication Failure tells the app to forget its
         * side and pair again (PODPK-4). */
        ESP_LOGW(TAG, "a bond without a passkey (or unknown): forgotten, the phone pairs again");
        if (ble_gap_conn_find(pair_conn, &desc) == 0)
            ble_store_util_delete_peer(&desc.peer_id_addr);
        ble_gap_terminate(pair_conn, BLE_ERR_AUTH_FAIL);
        break;
    case POD_PAIR_ACT_CLEAR_BONDS: {
        int n = 0;
        ble_store_util_count(BLE_STORE_OBJ_TYPE_OUR_SEC, &n);
        int rc = ble_store_clear();
        ESP_LOGW(TAG, "Bluetooth bonds cleared with the PRG button (%d bond(s), rc %d)", n, rc);
        if (b->connected) ble_gap_terminate(pair_conn, BLE_ERR_AUTH_FAIL);
        break;
    }
    default: break;
    }
}

bool pod_ble_nimble_start(bool encrypted)
{
    want_encryption = encrypted;
    want_passkey = encrypted && POD_BLE_PASSKEY;
    pod_pair_init(&pair, want_passkey);
    events = xQueueCreate(EV_QUEUE_LEN, sizeof(ev_t));
    if (events == NULL) return false;
    uuid_from(&uuid_service, pod_ble_uuid_service);
    uuid_from(&uuid_tx, pod_ble_uuid_tx);
    uuid_from(&uuid_rx, pod_ble_uuid_rx);
    uuid_from(&uuid_status, pod_ble_uuid_status);
    if (encrypted) chrs[1].flags |= BLE_GATT_CHR_F_WRITE_ENC;
    /* And with a key made by passkey entry (MITM-protected). */
    if (want_passkey) chrs[1].flags |= BLE_GATT_CHR_F_WRITE_AUTHEN;

    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Bluetooth controller failed to start (%s)", esp_err_to_name(err));
        return false;
    }
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.reset_cb = on_reset;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;
    /* LE Secure Connections, bonded; passkey entry with the pod's OLED (DisplayOnly) and MITM
     * protection asked for (PODPK-1), else Just Works. The phone, a keyboard and a display,
     * types the passkey. */
    ble_hs_cfg.sm_io_cap = want_passkey ? BLE_SM_IO_CAP_DISP_ONLY : BLE_SM_IO_CAP_NO_IO;
    ble_hs_cfg.sm_bonding = 1;
    ble_hs_cfg.sm_mitm = want_passkey ? 1 : 0;
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
    if (want_encryption) {
        int n = 0;
        ble_store_util_count(BLE_STORE_OBJ_TYPE_OUR_SEC, &n);
        ESP_LOGI(TAG, "%d phone(s) paired; %s", n,
                 want_passkey ? "pairing with a passkey on the OLED" : "pairing: Just Works");
        clear_button_start();
    }
    nimble_port_freertos_init(host_task);
#if CONFIG_ATALAIA_OLED_STATUS
    extern const hal_oled_ops_t hal_esp_oled_ops;
    if (want_passkey) pod_display_start(&hal_esp_oled_ops, read_view);
#endif
    return true;
}

void pod_ble_nimble_poll(pod_ble_t *b)
{
    ev_t e;
    while (events != NULL && xQueueReceive(events, &e, 0) == pdTRUE) {
        switch (e.kind) {
        case EV_CONNECT:
            pair_conn = e.conn;
            pod_ble_on_connect(b, e.conn);
            pod_pair_on_connect(&pair, now_ms());
            break;
        case EV_DISCONNECT:
            pod_ble_on_disconnect(b);
            pod_pair_on_disconnect(&pair, now_ms());
            break;
        case EV_ENCRYPTION:
            pod_ble_on_security(b, e.flag, e.authenticated);
            if (want_encryption) {
                act(b, pod_pair_on_encryption(&pair, (pod_pair_result_t)e.chr, e.flag,
                                              e.authenticated, now_ms()));
            }
            break;
        case EV_PASSKEY: pod_pair_on_passkey(&pair, e.passkey, now_ms()); break;
        case EV_SUBSCRIBE: pod_ble_on_subscribe(b, (pod_ble_chr_t)e.chr, e.flag); break;
        case EV_MTU: pod_ble_on_mtu(b, e.value); break;
        case EV_WRITE: pod_ble_on_write(b, e.data, e.len); break;
        default: break;
        }
    }
    if (!want_encryption) return;
    uint32_t t = now_ms();
    act(b, pod_pair_tick(&pair, t, clear_button_down()));
    oled_pair_view_t v;
    pod_pair_view(&pair, t, &v);
    taskENTER_CRITICAL(&view_lock);
    view_copy = v;
    taskEXIT_CRITICAL(&view_lock);
}

void pod_ble_nimble_set_status(const uint8_t status[3])
{
    taskENTER_CRITICAL(&status_lock);
    memcpy(status_copy, status, sizeof(status_copy));
    taskEXIT_CRITICAL(&status_lock);
}
