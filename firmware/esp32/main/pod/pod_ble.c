/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's GATT service, apart from the Bluetooth stack (see pod_ble.h).
 */
#include "pod_ble.h"

#include <stdio.h>
#include <string.h>

/* 4174616c-6169-6100-0000-0000000000xx: "Atalaia" in ASCII, then the
 * characteristic's number; least significant byte first. */
#define POD_UUID(last)                                                                             \
    {                                                                                              \
        (last), 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x61, 0x69, 0x61, 0x6c, 0x61,      \
            0x74, 0x41                                                                             \
    }

const uint8_t pod_ble_uuid_service[16] = POD_UUID(0x00);
const uint8_t pod_ble_uuid_tx[16] = POD_UUID(0x01);
const uint8_t pod_ble_uuid_rx[16] = POD_UUID(0x02);
const uint8_t pod_ble_uuid_status[16] = POD_UUID(0x03);

#define AD_FLAGS         0x01
#define AD_UUID128_ALL   0x07
#define AD_NAME_COMPLETE 0x09
#define AD_FLAG_GENERAL  0x02 /* LE General Discoverable Mode */
#define AD_FLAG_NO_BREDR 0x04 /* BR/EDR Not Supported */

void pod_ble_init(pod_ble_t *b, pod_t *pod, const pod_ble_stack_t *stack, bool require_encryption)
{
    memset(b, 0, sizeof(*b));
    b->pod = pod;
    b->stack = *stack;
    b->require_encryption = require_encryption;
    b->mtu = POD_BLE_MTU_MIN;
    b->status[0] = 0xFF;
    b->status[1] = 0x80;
}

size_t pod_ble_adv_data(uint8_t *out, size_t cap)
{
    if (cap < 3 + 18) return 0;
    size_t n = 0;
    out[n++] = 2;
    out[n++] = AD_FLAGS;
    out[n++] = AD_FLAG_GENERAL | AD_FLAG_NO_BREDR;
    out[n++] = 17;
    out[n++] = AD_UUID128_ALL;
    memcpy(out + n, pod_ble_uuid_service, 16);
    return n + 16;
}

size_t pod_ble_scan_response(const char *name, uint8_t *out, size_t cap)
{
    size_t len = strlen(name);
    if (len > 29) len = 29; /* 31 bytes of scan response, less the length and type */
    if (cap < len + 2) return 0;
    out[0] = (uint8_t)(len + 1);
    out[1] = AD_NAME_COMPLETE;
    memcpy(out + 2, name, len);
    return len + 2;
}

void pod_ble_device_name(const uint8_t addr_le[6], char out[POD_BLE_NAME_SIZE])
{
    snprintf(out, POD_BLE_NAME_SIZE, POD_BLE_NAME_PREFIX "%02X%02X", addr_le[1], addr_le[0]);
}

/* ---- The link -------------------------------------------------------------------- */

static void update(pod_ble_t *b)
{
    bool ready = b->connected && b->tx_subscribed && (b->encrypted || !b->require_encryption);
    if (ready == b->ready) return;
    b->ready = ready;
    if (ready) {
        /* The phone is listening: the link is active, and it learns who we are. */
        pod_set_link_up(b->pod, POD_LINK_BLE, true);
        pod_set_link_active(b->pod, POD_LINK_BLE);
        pod_send_ident(b->pod, POD_LINK_BLE);
        b->status_due = b->status_subscribed;
        pod_ble_flush(b);
    } else {
        b->queued = 0;
        pod_set_link_up(b->pod, POD_LINK_BLE, false);
    }
}

void pod_ble_on_connect(pod_ble_t *b, uint16_t conn)
{
    b->connected = true;
    b->conn = conn;
    b->encrypted = false;
    b->tx_subscribed = false;
    b->status_subscribed = false;
    b->mtu = POD_BLE_MTU_MIN;
    b->queued = 0;
    b->count.connections++;
    update(b);
}

void pod_ble_on_disconnect(pod_ble_t *b)
{
    b->connected = false;
    b->encrypted = false;
    b->tx_subscribed = false;
    b->status_subscribed = false;
    b->mtu = POD_BLE_MTU_MIN;
    update(b);
}

void pod_ble_on_encryption(pod_ble_t *b, bool encrypted)
{
    if (!b->connected) return;
    b->encrypted = encrypted;
    update(b);
}

void pod_ble_on_subscribe(pod_ble_t *b, pod_ble_chr_t chr, bool notify)
{
    if (!b->connected) return;
    if (chr == POD_BLE_TX) {
        b->tx_subscribed = notify;
    } else {
        b->status_subscribed = notify;
        if (notify) b->status_due = true;
    }
    update(b);
    pod_ble_flush(b);
}

void pod_ble_on_mtu(pod_ble_t *b, uint16_t mtu)
{
    b->mtu = mtu < POD_BLE_MTU_MIN ? POD_BLE_MTU_MIN : mtu;
}

void pod_ble_on_write(pod_ble_t *b, const uint8_t *data, size_t len)
{
    if (!b->connected) return;
    if (b->require_encryption && !b->encrypted) {
        b->count.writes_refused++; /* the stack refuses these too (an encrypted write only) */
        return;
    }
    b->count.writes++;
    pod_feed(b->pod, POD_LINK_BLE, data, len);
}

/* ---- Out ------------------------------------------------------------------------- */

int pod_ble_send_frame(pod_ble_t *b, const uint8_t *frame, size_t len)
{
    if (!b->ready || len > sizeof(b->queue) - b->queued) {
        b->count.frames_dropped++;
        return -1;
    }
    memcpy(b->queue + b->queued, frame, len);
    b->queued += len;
    b->count.frames_out++;
    pod_ble_flush(b);
    return 0;
}

void pod_ble_flush(pod_ble_t *b)
{
    if (!b->ready) return;
    size_t piece = (size_t)b->mtu - 3;
    while (b->queued > 0) {
        size_t n = b->queued < piece ? b->queued : piece;
        int r = b->stack.notify(b->stack.ctx, b->conn, POD_BLE_TX, b->queue, n);
        if (r > 0) return; /* busy: the rest goes at the next flush */
        if (r < 0) {
            b->queued = 0; /* the link is failing; the frames' own resends repair it */
            b->count.frames_dropped++;
            return;
        }
        b->count.notifications++;
        memmove(b->queue, b->queue + n, b->queued - n);
        b->queued -= n;
    }
    if (b->status_due && b->status_subscribed) {
        int r = b->stack.notify(b->stack.ctx, b->conn, POD_BLE_STATUS, b->status, 3);
        if (r <= 0) b->status_due = false;
    }
}

void pod_ble_set_status(pod_ble_t *b, const uint8_t status[3])
{
    if (memcmp(b->status, status, 3) == 0) return;
    memcpy(b->status, status, 3);
    b->status_due = true;
    pod_ble_flush(b);
}
