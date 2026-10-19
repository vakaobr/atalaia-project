/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's Bluetooth LE GATT service (protocol/capability-proxy.md,
 * decision A9), apart from the Bluetooth stack:
 *
 *   service    4174616c-6169-6100-0000-000000000000  advertised; name atalaia-pod-XXXX
 *   Pod TX     ...0001  Notify                  the pod's frames, cut to the MTU
 *   Pod RX     ...0002  Write Without Response  the phone's frames (an encrypted link only)
 *   Pod Status ...0003  Read, Notify            battery, last RSSI, flags (3 bytes)
 *
 * One phone at a time. The link is ready, and the pod sends its IDENT, once
 * the phone is connected, the link is encrypted (LE Secure Connections,
 * decision PF4) and Pod TX notifications are on; only then do frames go out.
 * A frame longer than one notification (MTU - 3 bytes) is sent in pieces,
 * which the phone joins (the framing finds the boundaries). When the stack
 * is busy the bytes wait in a small queue and go at the next pod_ble_flush().
 *
 * The NimBLE glue (pod_ble_nimble.c, ESP-IDF only) calls these functions
 * from the pod task; the host tests (test/test_ble_gatt_stub.c) and the host
 * pod drive them with a stub stack.
 */
#ifndef ATALAIA_POD_BLE_H
#define ATALAIA_POD_BLE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "pod.h"

#define POD_BLE_UUID_SERVICE "4174616c-6169-6100-0000-000000000000"
#define POD_BLE_UUID_TX      "4174616c-6169-6100-0000-000000000001"
#define POD_BLE_UUID_RX      "4174616c-6169-6100-0000-000000000002"
#define POD_BLE_UUID_STATUS  "4174616c-6169-6100-0000-000000000003"

/* The same UUIDs as they go over the air (least significant byte first). */
extern const uint8_t pod_ble_uuid_service[16];
extern const uint8_t pod_ble_uuid_tx[16];
extern const uint8_t pod_ble_uuid_rx[16];
extern const uint8_t pod_ble_uuid_status[16];

#define POD_BLE_NAME_PREFIX "atalaia-pod-"
#define POD_BLE_NAME_SIZE   17 /* "atalaia-pod-XXXX" and its NUL */
#define POD_BLE_MTU_MIN     23
#define POD_BLE_MTU_WANTED  247 /* P3-6: the phone asks for at least 247 */
#define POD_BLE_QUEUE       1024

typedef enum {
    POD_BLE_TX = 0,     /* Pod TX */
    POD_BLE_STATUS = 1, /* Pod Status */
} pod_ble_chr_t;

typedef struct {
    /* One notification (at most MTU - 3 bytes). Returns 0 when sent, 1 when
     * the stack is busy (try again later), -1 when it failed. */
    int (*notify)(void *ctx, uint16_t conn, pod_ble_chr_t chr, const uint8_t *data, size_t len);
    void *ctx;
} pod_ble_stack_t;

typedef struct {
    uint32_t frames_out;     /* frames queued for Pod TX */
    uint32_t notifications;  /* notifications sent */
    uint32_t frames_dropped; /* the link was not ready, or the queue was full */
    uint32_t writes;         /* Pod RX writes taken */
    uint32_t writes_refused; /* Pod RX writes on a link not encrypted */
    uint32_t connections;
} pod_ble_counters_t;

typedef struct {
    pod_ble_stack_t stack;
    pod_t *pod;
    bool require_encryption;

    bool connected;
    bool encrypted;
    bool tx_subscribed;
    bool status_subscribed;
    bool ready;
    uint16_t conn;
    uint16_t mtu;

    uint8_t queue[POD_BLE_QUEUE];
    size_t queued;

    uint8_t status[3];
    bool status_due; /* a changed status still to notify */

    pod_ble_counters_t count;
} pod_ble_t;

void pod_ble_init(pod_ble_t *b, pod_t *pod, const pod_ble_stack_t *stack, bool require_encryption);

/* The advertising data: flags and the complete list of 128-bit service UUIDs. */
size_t pod_ble_adv_data(uint8_t *out, size_t cap);

/* The scan response: the complete local name. */
size_t pod_ble_scan_response(const char *name, uint8_t *out, size_t cap);

/* "atalaia-pod-XXXX": the last 4 hex digits of the address (addr_le[0] is its last byte). */
void pod_ble_device_name(const uint8_t addr_le[6], char out[POD_BLE_NAME_SIZE]);

/* Stack events. */
void pod_ble_on_connect(pod_ble_t *b, uint16_t conn);
void pod_ble_on_disconnect(pod_ble_t *b);
void pod_ble_on_encryption(pod_ble_t *b, bool encrypted);
void pod_ble_on_subscribe(pod_ble_t *b, pod_ble_chr_t chr, bool notify);
void pod_ble_on_mtu(pod_ble_t *b, uint16_t mtu);

/* A Pod RX write: the bytes go to the proxy (pod_feed on the BLE link). */
void pod_ble_on_write(pod_ble_t *b, const uint8_t *data, size_t len);

/* A frame for the phone (the pod's link_write for POD_LINK_BLE). Returns 0, or -1 if dropped. */
int pod_ble_send_frame(pod_ble_t *b, const uint8_t *frame, size_t len);

/* Sends what waits in the queue, and a changed status. */
void pod_ble_flush(pod_ble_t *b);

/* The Pod Status bytes: notified when they change, read at any time. */
void pod_ble_set_status(pod_ble_t *b, const uint8_t status[3]);

#endif /* ATALAIA_POD_BLE_H */
