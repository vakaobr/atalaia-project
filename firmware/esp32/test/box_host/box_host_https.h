/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The host box's HTTPS to the field controller: what fw_update_esp.c gives a
 * mode fetch on the Field Box (fw_update_esp_net), over mbedTLS's own sockets
 * instead of the Wi-Fi and esp_http_client, with the same field CA pin
 * (main/field_ca_pin.c). The firmware's own mode_fetch.c runs over it against
 * the real controller (controller/tests/test_box_mode_fetch_e2e.py).
 */
#ifndef ATALAIA_BOX_HOST_HTTPS_H
#define ATALAIA_BOX_HOST_HTTPS_H

#include <stdint.h>

#include "fw_update.h"

/* The operations, with HTTPS pinned to ca_sha256 (the join's key 13); warn gets why a
 * connection or a certificate is refused. As fw_update_esp_net: a caller copies the struct and
 * sets its own cancelled and progress. */
const fw_io_t *box_host_https_net(const uint8_t ca_sha256[32], void (*warn)(const char *why));

#endif /* ATALAIA_BOX_HOST_HTTPS_H */
