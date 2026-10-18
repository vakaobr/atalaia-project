/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem logic (ADR-P2-4, ADR-P2-5): the bridge between the
 * field controller (frames on a serial link) and the LoRa radio.
 *
 *   host --TX frame (header + plaintext)--> encrypt (AES-CCM) --> radio
 *   radio --packet--> dedupe, decrypt (epoch window) --RX frame--> host
 *
 * The game key lives in RAM only: the controller sends it with CONFIGURE
 * after every connect. The controller owns its own epoch and sequence
 * numbers; the modem refuses any TX whose (epoch, seq) is not above the
 * last one it sent, so a controller bug cannot reuse a nonce.
 *
 * The controller does not relay (ADR-P2-6), so the modem never
 * rebroadcasts. Plain C with injected I/O: no ESP-IDF dependency.
 */
#ifndef ATALAIA_MODEM_H
#define ATALAIA_MODEM_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/packet.h"
#include "modem_framing.h"
#include "radio/radio_protocol.h"

#define MODEM_DEDUPE_SIZE      64
#define MODEM_DEDUPE_EXPIRY_MS 30000
#define MODEM_MAX_HOPS         3 /* ADR-P2-6: the configured maximum never exceeds 3 */

typedef struct {
    /* Writes bytes to the serial link. Returns 0 on success. */
    int (*serial_write)(void *ctx, const uint8_t *buf, size_t len);
    /* Queues an encrypted packet for the radio; the outcome comes back
     * through modem_on_tx_result() with the same tag. */
    bool (*radio_send)(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag);
    /* Tunes the radio. Returns 0 on success, -1 if refused. */
    int (*set_channel)(void *ctx, uint32_t freq_hz);
    /* Remaining duty-cycle budget in ms. */
    uint32_t (*duty_cycle_remaining_ms)(void *ctx);
    /* Monotonic milliseconds. */
    uint32_t (*now_ms)(void *ctx);
    void *ctx;
} modem_io_t;

typedef struct {
    uint16_t source;
    uint32_t nonce_ctr; /* (epoch << 16) | seq */
    uint32_t seen_ms;
    bool used;
} modem_dedupe_entry_t;

typedef struct {
    uint32_t rx_ok;        /* packets forwarded to the host */
    uint32_t rx_dropped;   /* not ours, not configured, own echo */
    uint32_t rx_auth_fail; /* MIC failed for every epoch in the window */
    uint32_t rx_dupes;     /* already forwarded (flood copies) */
    uint32_t tx_ok;
    uint32_t tx_fail;
    uint32_t cmds;
    uint32_t bad_frames;
} modem_counters_t;

typedef struct {
    modem_io_t io;
    const atalaia_crypto_ops_t *crypto;
    const char *fw_version;
    bool radio_present;
    uint16_t epoch_window;

    modem_decoder_t dec;
    atalaia_radio_proto_t rx; /* game key, per-source epochs (receive side) */
    bool configured;
    uint16_t game_id;
    uint16_t node_id;  /* the controller's own source id */
    uint16_t tx_epoch; /* the controller's epoch for its own packets */
    uint8_t max_hops;
    uint32_t channel_hz;
    bool tx_used;
    uint32_t last_tx_nonce; /* highest (epoch << 16) | seq sent */

    modem_dedupe_entry_t dedupe[MODEM_DEDUPE_SIZE];
    modem_counters_t count;
    uint32_t boot_ms;
} modem_t;

/*
 * Prepares the modem. radio_present says whether a radio chip answered at
 * boot; epoch_window is how many epochs above the last known one the
 * receive side tries (1 = ADR-P2-2's "epoch + 1" only). Sends nothing.
 */
void modem_init(modem_t *m, const modem_io_t *io, const atalaia_crypto_ops_t *crypto,
                const char *fw_version, bool radio_present, uint16_t epoch_window);

/* Sends an IDENT frame (on boot and on MODEM_CMD_IDENT). */
void modem_send_ident(modem_t *m);

/* Bytes from the serial link: complete frames are handled immediately. */
void modem_feed_serial(modem_t *m, const uint8_t *data, size_t len);

/* A packet from the radio, with its RSSI and SNR in dB. */
void modem_on_air_rx(modem_t *m, const uint8_t *pkt, size_t len, int8_t rssi, int8_t snr);

/* Outcome of a radio_send() call: tag is the packet's seq + 1. */
void modem_on_tx_result(modem_t *m, uint32_t tag, modem_tx_status_t status);

/* Handles one decoded frame (exposed for tests). */
void modem_handle_frame(modem_t *m, uint8_t type, const uint8_t *payload, size_t len);

#endif /* ATALAIA_MODEM_H */
