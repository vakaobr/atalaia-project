/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The field CA pin (field_ca_pin.h), moved out of fw_update_esp.c so the host
 * box runs the same check.
 */
#include "field_ca_pin.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "mbedtls/md.h"
#include "mbedtls/pk.h"

/* mbedTLS 3.x hides the certificate's fields behind MBEDTLS_PRIVATE (ESP-IDF 5.3); 2.28, the
 * host's (Debian), has them public. */
#ifndef MBEDTLS_PRIVATE
#define MBEDTLS_PRIVATE(member) member
#endif

static mbedtls_x509_crt placeholder_ca; /* never matches: the callback decides */

static void warn(const field_ca_pin_t *pin, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void warn(const field_ca_pin_t *pin, const char *fmt, ...)
{
    if (pin->warn == NULL) return;
    char why[200];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(why, sizeof(why), fmt, ap);
    va_end(ap);
    pin->warn(why);
}

bool field_ca_pin_is_ca(const field_ca_pin_t *pin, const mbedtls_x509_crt *crt)
{
    uint8_t h[32];
    const mbedtls_md_info_t *sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    return sha256 != NULL && mbedtls_md(sha256, crt->raw.p, crt->raw.len, h) == 0 &&
           memcmp(h, pin->sha256, 32) == 0;
}

/* Whether ca (a certificate the server sent) issued and signed child. */
static bool signed_by(const field_ca_pin_t *pin, const mbedtls_x509_crt *child,
                      mbedtls_x509_crt *ca)
{
    if (!ca->MBEDTLS_PRIVATE(ca_istrue)) {
        warn(pin, "the field CA is not marked as a CA");
        return false;
    }
    if (child->issuer_raw.len != ca->subject_raw.len ||
        memcmp(child->issuer_raw.p, ca->subject_raw.p, ca->subject_raw.len) != 0) {
        warn(pin, "the certificate's issuer is not the field CA's name");
        return false;
    }
    if (!mbedtls_pk_can_do(&ca->pk, child->MBEDTLS_PRIVATE(sig_pk))) {
        warn(pin, "the field CA's key cannot check this signature type");
        return false;
    }
    const mbedtls_md_info_t *md = mbedtls_md_info_from_type(child->MBEDTLS_PRIVATE(sig_md));
    unsigned char hash[MBEDTLS_MD_MAX_SIZE];
    int ret = md == NULL ? -1 : mbedtls_md(md, child->tbs.p, child->tbs.len, hash);
    if (ret != 0) {
        warn(pin, "hashing the certificate failed (-0x%04x)", (unsigned)-ret);
        return false;
    }
    ret = mbedtls_pk_verify_ext(child->MBEDTLS_PRIVATE(sig_pk), child->MBEDTLS_PRIVATE(sig_opts),
                                &ca->pk, child->MBEDTLS_PRIVATE(sig_md), hash,
                                mbedtls_md_get_size(md), child->MBEDTLS_PRIVATE(sig).p,
                                child->MBEDTLS_PRIVATE(sig).len);
    if (ret != 0) warn(pin, "the field CA's signature does not verify (-0x%04x)", (unsigned)-ret);
    return ret == 0;
}

/* As ESP-IDF's certificate bundle does: mbedTLS marks "not trusted" on the
 * certificate it could not chain to a trusted CA (on the bench, the
 * controller's own certificate, though the server sent the field CA after
 * it). Clear it only where the field CA of the join, found among the
 * certificates the server sent, is that certificate itself or issued and
 * signed it; every other flag stays. */
int field_ca_pin_verify(void *ctx, mbedtls_x509_crt *crt, int depth, uint32_t *flags)
{
    const field_ca_pin_t *pin = (const field_ca_pin_t *)ctx;
    if (*flags & MBEDTLS_X509_BADCERT_NOT_TRUSTED) {
        bool anchored = field_ca_pin_is_ca(pin, crt);
        for (mbedtls_x509_crt *ca = crt->next; !anchored && ca != NULL; ca = ca->next) {
            anchored = field_ca_pin_is_ca(pin, ca) && signed_by(pin, crt, ca);
        }
        if (anchored) {
            *flags &= ~(uint32_t)MBEDTLS_X509_BADCERT_NOT_TRUSTED;
        } else {
            warn(pin, "certificate at depth %d: not the field CA of the join, nor signed by it",
                 depth);
        }
    }
    if (depth == 0 && *flags != 0 && pin->warn != NULL) {
        /* Say why a handshake is refused (name, usage, signature...). */
        char info[160];
        mbedtls_x509_crt_verify_info(info, sizeof(info), "", *flags);
        /* One line per flag: joined into one. */
        size_t n = strlen(info);
        while (n > 0 && info[n - 1] == '\n') info[--n] = '\0';
        for (char *c = info; *c; c++) {
            if (*c == '\n') *c = ';';
        }
        warn(pin, "the controller's certificate: %s", info);
    }
    return 0;
}

void field_ca_pin_attach(mbedtls_ssl_config *conf, field_ca_pin_t *pin)
{
    mbedtls_ssl_conf_authmode(conf, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_ca_chain(conf, &placeholder_ca, NULL);
    mbedtls_ssl_conf_verify(conf, field_ca_pin_verify, pin);
}
