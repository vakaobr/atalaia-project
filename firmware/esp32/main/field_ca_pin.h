/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * HTTPS to the field controller trusts exactly one certificate authority: the
 * field CA whose SHA-256 the signed join payload carries (key 13). The
 * controller sends it after its own certificate
 * (controller/atalaia_controller/tls.py); the verify callback clears "not
 * trusted" on that certificate alone, so the chain must end at it, the
 * controller's certificate must be signed by it and carry the host name of the
 * address (key 14), as mbedTLS checks. The same pattern as ESP-IDF's own
 * certificate bundle (a placeholder CA list and a verify callback).
 *
 * Only mbedTLS (2.28 or 3.x), no platform: the Field Box's HTTPS
 * (fw_update_esp.c, over esp_http_client) and the host box's
 * (test/box_host/box_host_https.c, over mbedTLS's own sockets, the end-to-end
 * test against the real controller) attach the same check.
 */
#ifndef ATALAIA_FIELD_CA_PIN_H
#define ATALAIA_FIELD_CA_PIN_H

#include <stdbool.h>
#include <stdint.h>

#include "mbedtls/ssl.h"
#include "mbedtls/x509_crt.h"

typedef struct {
    uint8_t sha256[32];            /* the join's field CA (key 13) */
    void (*warn)(const char *why); /* why a certificate is refused; NULL: silent */
} field_ca_pin_t;

/* Whether crt is the pinned field CA (the SHA-256 of its DER). */
bool field_ca_pin_is_ca(const field_ca_pin_t *pin, const mbedtls_x509_crt *crt);

/* mbedTLS's verify callback (ctx: the field_ca_pin_t): clears "not trusted" only on the field CA
 * itself or a certificate it issued and signed, found among those the server sent; every other
 * flag stays. */
int field_ca_pin_verify(void *ctx, mbedtls_x509_crt *crt, int depth, uint32_t *flags);

/* A client configuration that requires a certificate and checks it with field_ca_pin_verify
 * (pin must outlive the configuration's handshakes). */
void field_ca_pin_attach(mbedtls_ssl_config *conf, field_ca_pin_t *pin);

#endif /* ATALAIA_FIELD_CA_PIN_H */
