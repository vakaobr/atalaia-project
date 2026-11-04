/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's GATT service on the NimBLE stack (ESP-IDF only, built when
 * CONFIG_ATALAIA_POD_MODE and CONFIG_ATALAIA_POD_BLE are set). The stack's
 * events (connections, encryption, subscriptions, the MTU, Pod RX writes)
 * are queued by the NimBLE host task and handed to pod_ble.c on the pod task
 * by pod_ble_nimble_poll(), so the proxy runs on one task only.
 */
#ifndef ATALAIA_POD_BLE_NIMBLE_H
#define ATALAIA_POD_BLE_NIMBLE_H

#include <stdbool.h>
#include <stdint.h>

#include "pod_ble.h"

/* The stack ops for pod_ble_init(): notifications through NimBLE. */
extern const pod_ble_stack_t pod_ble_nimble_stack;

/*
 * Starts the controller and the NimBLE host with the pod's service and
 * advertises it. encrypted: Pod RX takes only encrypted writes, and the pod
 * asks the phone to pair (LE Secure Connections, bonded): with a passkey on
 * the OLED and MITM protection (CONFIG_ATALAIA_POD_BLE_PASSKEY, decisions
 * PODPK-1 to PODPK-11; pod_pair.h, pod_display.h), else Just Works. Starts
 * the OLED task for the passkey and reads the bond-clearing button
 * (CONFIG_ATALAIA_POD_BOND_CLEAR_PIN) in pod_ble_nimble_poll().
 * Returns false if the stack did not start.
 */
bool pod_ble_nimble_start(bool encrypted);

/* Hands the queued stack events to b and to the pairing (pod_pair.h), and carries out what the
 * pairing decides (drop a link, forget a bond, clear them all). Call often from the pod task. */
void pod_ble_nimble_poll(pod_ble_t *b);

/* The Pod Status bytes a read returns. */
void pod_ble_nimble_set_status(const uint8_t status[3]);

#endif /* ATALAIA_POD_BLE_NIMBLE_H */
