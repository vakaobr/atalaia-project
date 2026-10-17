/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * AES-128-CCM crypto backend using mbedtls. This file is compiled only
 * when libmbedcrypto is available (see CMakeLists.txt).
 */
#include "atalaia/packet.h"

#include <mbedtls/ccm.h>
#include <string.h>

static int mbedtls_ccm_encrypt(void *ctx, const uint8_t *key, const uint8_t *nonce,
                               size_t nonce_len, const uint8_t *aad, size_t aad_len,
                               const uint8_t *plaintext, size_t pt_len, uint8_t *ciphertext,
                               uint8_t *tag, size_t tag_len)
{
    (void)ctx;
    mbedtls_ccm_context ccm;
    mbedtls_ccm_init(&ccm);

    int rc = mbedtls_ccm_setkey(&ccm, MBEDTLS_CIPHER_ID_AES, key, 128);
    if (rc != 0) {
        mbedtls_ccm_free(&ccm);
        return -1;
    }

    rc = mbedtls_ccm_encrypt_and_tag(&ccm, pt_len, nonce, nonce_len, aad, aad_len, plaintext,
                                     ciphertext, tag, tag_len);
    mbedtls_ccm_free(&ccm);
    return rc == 0 ? 0 : -1;
}

static int mbedtls_ccm_decrypt(void *ctx, const uint8_t *key, const uint8_t *nonce,
                               size_t nonce_len, const uint8_t *aad, size_t aad_len,
                               const uint8_t *ciphertext, size_t ct_len, uint8_t *plaintext,
                               const uint8_t *tag, size_t tag_len)
{
    (void)ctx;
    mbedtls_ccm_context ccm;
    mbedtls_ccm_init(&ccm);

    int rc = mbedtls_ccm_setkey(&ccm, MBEDTLS_CIPHER_ID_AES, key, 128);
    if (rc != 0) {
        mbedtls_ccm_free(&ccm);
        return -1;
    }

    rc = mbedtls_ccm_auth_decrypt(&ccm, ct_len, nonce, nonce_len, aad, aad_len, ciphertext,
                                  plaintext, tag, tag_len);
    mbedtls_ccm_free(&ccm);
    return rc == 0 ? 0 : -1;
}

const atalaia_crypto_ops_t atalaia_crypto_mbedtls = {
    .encrypt = mbedtls_ccm_encrypt, .decrypt = mbedtls_ccm_decrypt, .ctx = NULL};
