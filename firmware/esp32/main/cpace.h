/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * CPace, CPACE-X25519-SHA512 (draft-irtf-cfrg-cpace-14): the pairing code's
 * key exchange (protocol/adoption.md section 7, decision AD-10), on Monocypher
 * 4.0.2 (components/monocypher): crypto_x25519, crypto_elligator_map and the
 * optional part's SHA-512. Checked against the draft's Appendix B.1 and B.1.10
 * (protocol/vectors/pairing.json), as is the Python side
 * (simulator/atalaia_sim/cpace.py). Platform-free.
 */
#ifndef ATALAIA_CPACE_H
#define ATALAIA_CPACE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CPACE_POINT_SIZE 32
#define CPACE_ISK_SIZE   64
#define CPACE_GS_MAX     256 /* the generator string, for PRS, CI and sid of up to 64 bytes */

/* The draft's generator_string(DSI "CPace255", PRS, CI, sid, 128). Returns its length (0 if
 * it does not fit). */
size_t cpace_generator_string(const uint8_t *prs, size_t prs_len, const uint8_t *ci, size_t ci_len,
                              const uint8_t *sid, size_t sid_len, uint8_t *out, size_t cap);

/* The generator g: Elligator 2 of the first 32 bytes of SHA-512(the generator string). */
bool cpace_generator(const uint8_t *prs, size_t prs_len, const uint8_t *ci, size_t ci_len,
                     const uint8_t *sid, size_t sid_len, uint8_t g[CPACE_POINT_SIZE]);

/* X25519(scalar, u) (RFC 7748, clamped); all zeros for the neutral element. */
void cpace_scalar_mult(const uint8_t scalar[32], const uint8_t u[CPACE_POINT_SIZE],
                       uint8_t out[CPACE_POINT_SIZE]);

/* As cpace_scalar_mult; false (the abort case) when the result is the neutral element. */
bool cpace_scalar_mult_vfy(const uint8_t scalar[32], const uint8_t u[CPACE_POINT_SIZE],
                           uint8_t out[CPACE_POINT_SIZE]);

/* ISK = SHA-512(lv_cat("CPace255_ISK", sid, K) || lv_cat(Ya, ADa) || lv_cat(Yb, ADb)). */
void cpace_isk_ir(const uint8_t *sid, size_t sid_len, const uint8_t k[CPACE_POINT_SIZE],
                  const uint8_t ya[CPACE_POINT_SIZE], const uint8_t *ada, size_t ada_len,
                  const uint8_t yb[CPACE_POINT_SIZE], const uint8_t *adb, size_t adb_len,
                  uint8_t isk[CPACE_ISK_SIZE]);

#endif /* ATALAIA_CPACE_H */
