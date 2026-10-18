/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Radio protocol glue: encodes core events as Skirmesh-RF packets for
 * the radio TX queue, and decodes received packets into node_runner
 * inputs.  Owns the epoch counter and nonce safety invariant.
 *
 * Epoch persistence (ADR-P2-2, RFC 0001 section 3):
 *   nonce_ctr = (epoch << 16) | seq
 *   - Epoch is read from NVS, incremented and persisted BEFORE the first
 *     TX after boot.
 *   - At seq wrap (65535 -> 0): epoch increments and is persisted BEFORE
 *     transmitting with seq=0.
 *   - If an NVS write fails: tx_blocked is set and the radio refuses
 *     to transmit.
 *   - At epoch 65535: tx_blocked is set (nonce space exhausted).
 *
 * Receiver epoch trial (ADR-P2-2):
 *   A per-source table tracks each sender's last authenticated epoch.
 *   On receive the receiver tries the stored epoch first, then epoch+1.
 *   Lower epochs are never accepted.
 */
#ifndef ATALAIA_RADIO_PROTOCOL_H
#define ATALAIA_RADIO_PROTOCOL_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/codec.h"
#include "atalaia/event.h"
#include "atalaia/msg_codec.h"
#include "atalaia/packet.h"
#include "radio_task.h"

/* ---- NVS abstraction (function pointers for testability) ------------------ */

typedef struct {
    int (*read_epoch)(void *ctx, uint16_t *epoch);      /* 0=ok, -1=not found, -2=error */
    int (*write_epoch)(void *ctx, uint16_t epoch);      /* 0=ok, -1=error */
    int (*read_key)(void *ctx, uint8_t key[16]);        /* 0=ok, -1=not found */
    int (*write_key)(void *ctx, const uint8_t key[16]); /* 0=ok, -1=error */
    int (*erase_key)(void *ctx);                        /* 0=ok, -1=error */
    void *ctx;
} atalaia_radio_nvs_ops_t;

/* ---- Per-source epoch tracking -------------------------------------------- */

#define RADIO_PROTO_MAX_SOURCES 32

typedef struct {
    uint16_t source;
    uint16_t epoch;
    bool valid;
} atalaia_radio_source_epoch_t;

/* ---- Radio protocol state ------------------------------------------------- */

typedef struct {
    uint16_t game_id;
    uint16_t node_id;
    uint16_t epoch;
    uint16_t seq;
    uint8_t game_key[ATALAIA_RF_KEY_SIZE];
    bool has_key;
    bool tx_blocked;
    const atalaia_crypto_ops_t *crypto;
    const atalaia_radio_nvs_ops_t *nvs;

    /* Per-source epoch table for receiver-side epoch trial. */
    atalaia_radio_source_epoch_t source_epochs[RADIO_PROTO_MAX_SOURCES];
} atalaia_radio_proto_t;

/*
 * Initialise the radio protocol layer.
 * nvs may be NULL (NVS disabled; epoch starts at 0, no persistence).
 */
void atalaia_radio_proto_init(atalaia_radio_proto_t *rp, uint16_t game_id, uint16_t node_id,
                              const atalaia_crypto_ops_t *crypto,
                              const atalaia_radio_nvs_ops_t *nvs);

/*
 * Boot-time epoch cycle: read stored epoch, increment, persist.
 * Must be called once after init and before the first TX.
 * Returns true on success; false if NVS write failed (tx_blocked set).
 * If nvs is NULL this is a no-op that returns true.
 */
bool atalaia_radio_proto_boot_epoch(atalaia_radio_proto_t *rp);

/* Set the game key (from NFC tap or NVS restore). */
void atalaia_radio_proto_set_key(atalaia_radio_proto_t *rp, const uint8_t key[ATALAIA_RF_KEY_SIZE]);

/* Set the epoch (for testing or manual resync). */
void atalaia_radio_proto_set_epoch(atalaia_radio_proto_t *rp, uint16_t epoch);

/*
 * Set a source's epoch in the receiver table (resync from HELLO/STATE).
 */
void atalaia_radio_proto_set_source_epoch(atalaia_radio_proto_t *rp, uint16_t source,
                                          uint16_t epoch);

/*
 * Encode an event and queue it for TX. Returns true on success.
 * Returns false if tx_blocked, no key, encode failure, or queue full.
 */
bool atalaia_radio_proto_send_event(atalaia_radio_proto_t *rp, const atalaia_event_t *ev,
                                    const char *data_json);

/*
 * Encode a STATE message and queue it for TX.
 */
bool atalaia_radio_proto_send_state(atalaia_radio_proto_t *rp, const atalaia_state_msg_t *state);

/*
 * Process a received packet.  Decrypts and validates it using per-source
 * epoch trial: tries the source's last known epoch, then epoch+1.
 * Returns true if the packet was valid.
 */
bool atalaia_radio_proto_on_recv(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx_msg,
                                 atalaia_header_t *out_hdr, uint8_t *out_payload,
                                 size_t *out_payload_len);

#endif /* ATALAIA_RADIO_PROTOCOL_H */
