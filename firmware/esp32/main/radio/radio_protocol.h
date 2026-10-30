/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Radio protocol glue: encodes core events as Skirmesh-RF packets for
 * the radio TX queue, and decodes received packets into node_runner
 * inputs.  Owns the epoch counter and nonce safety invariant.
 *
 * Epoch persistence (ADR-P2-2, RFC 0001 section 3 and its amendment of
 * 2026-10-22: the epoch is per game key):
 *   nonce_ctr = (epoch << 16) | seq
 *   - The epoch store keeps one record per recent game key (ATALAIA_EPOCH_KEYS,
 *     most recent first), each named by the key's tag (ATALAIA_EPOCH_TAG_SIZE
 *     bytes of HMAC-SHA256(game_key, "atalaia epoch tag")), never the key.
 *   - At boot (every join and every resume): a key with a record goes on at
 *     its epoch + 1; a new key starts at epoch 1, so a receiver new to the
 *     game (epochs 0..window) always hears it. A key whose record was pushed
 *     out by newer ones is remembered by its tag alone (retired): its epochs
 *     are unknown, so it is refused rather than started again at 1 (decisions
 *     BN-7, BN-19). The whole store is written in one atomic write BEFORE the
 *     first TX.
 *   - At seq wrap (65535 -> 0): epoch increments and is persisted BEFORE
 *     transmitting with seq=0.
 *   - If an NVS write fails: tx_blocked is set and the radio refuses
 *     to transmit.
 *   - At epoch 65535: tx_blocked is set (nonce space exhausted).
 *
 * Replay window (RFC 0001 Amendment 23): after a packet authenticates, its counter
 * (epoch << 16 | seq) goes through the source's 64-wide window (core/atalaia/replay.h); a counter
 * already seen or 64 or more below the highest is refused (on_recv_window returns false and sets
 * last_replay). This replaces the receivers' 30-second duplicate tables.
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
#include "atalaia/replay.h"
#include "radio_task.h"

/* ---- NVS abstraction (function pointers for testability) ------------------ */

#define ATALAIA_EPOCH_TAG_SIZE 8
#define ATALAIA_EPOCH_KEYS     16 /* game keys whose epoch is kept */
#define ATALAIA_EPOCH_RETIRED  48 /* older game keys, by their tag alone: refused */
#define ATALAIA_EPOCH_REC_SIZE (ATALAIA_EPOCH_TAG_SIZE + 2)
#define ATALAIA_EPOCH_STORE_MAX                                                                    \
    (4 + ATALAIA_EPOCH_KEYS * ATALAIA_EPOCH_REC_SIZE +                                             \
     ATALAIA_EPOCH_RETIRED * ATALAIA_EPOCH_TAG_SIZE)
#define ATALAIA_EPOCH_STORE_VER 2

/*
 * The epoch store is one blob: version (2), count n (0..ATALAIA_EPOCH_KEYS),
 * count r of retired tags (0..ATALAIA_EPOCH_RETIRED), 0, then n records of tag
 * (8 bytes) and epoch (u16 big-endian), most recently used first, then r
 * retired tags, most recently retired first. (Version 1, of the first builds
 * of the amendment: version, n, records; read with no retired tags.) write_epochs must replace the
 * whole blob atomically (NVS set_blob + commit; a file written aside and renamed): after a power
 * cut the store is either the old blob or the new one, never a mix.
 *
 * read_legacy_epoch reads the single u16 "epoch" of firmware before the
 * amendment (may be NULL). It is used only while no blob exists, and only
 * for the stored game the box resumes (the key it belonged to).
 */
typedef struct {
    int (*read_legacy_epoch)(void *ctx, uint16_t *epoch);           /* 0=ok, -1=none, -2=error */
    int (*read_epochs)(void *ctx, uint8_t *buf, size_t cap);        /* len, -1=none, -2=error */
    int (*write_epochs)(void *ctx, const uint8_t *buf, size_t len); /* 0=ok, -1=error */
    int (*read_key)(void *ctx, uint8_t key[16]);                    /* 0=ok, -1=not found */
    int (*write_key)(void *ctx, const uint8_t key[16]);             /* 0=ok, -1=error */
    int (*erase_key)(void *ctx);                                    /* 0=ok, -1=error */
    /* n random bytes from the hardware generator (0=ok, -1=error); may be NULL, which only a box
     * that has lost its epoch store needs (ATALAIA_EPOCH_LOST_MIN, decision SR-27). */
    int (*random_bytes)(void *ctx, uint8_t *buf, size_t n);
    void *ctx;
} atalaia_radio_nvs_ops_t;

/* ---- Per-source epoch tracking -------------------------------------------- */

/* One entry per source heard: its epoch and its replay window (about 24 bytes each). 64 holds a
 * field of 30 boxes with the controllers and spare (decision SR-24); a full table drops its oldest
 * entry, whose source is then met again as a new one. */
#define RADIO_PROTO_MAX_SOURCES 64

typedef struct {
    uint16_t source;
    uint16_t epoch;
    bool valid;
    /* A source met for the first time (or again after its slot was reused): its epoch may be a
     * recorded old packet's, so later packets may be searched further up (within the wide
     * search budget) until one authenticates in the normal window (decision BN-21). */
    bool provisional;
    /* The packets already accepted from this source (RFC 0001 Amendment 23, decision SR-20). */
    atalaia_replay_t replay;
} atalaia_radio_source_epoch_t;

/* The wide search (HELLO and TIME, and a provisional source's packets) costs up to 257
 * decryptions: at most once per source every ATALAIA_WIDE_GAP_MS, and ATALAIA_WIDE_PER_MIN
 * times a minute in all (decision BN-20). A node's HELLO is resent until it is
 * acknowledged (after 3, 6, 12, 24 s, then every 30 s: RFC 0001 Amendment 13), so a genuine one is
 * searched within a retry or two. */
#define ATALAIA_WIDE_GAP_MS  2000
#define ATALAIA_WIDE_PER_MIN 20
#define ATALAIA_WIDE_SOURCES 8

/* The deep search (RFC 0001 Amendment 24, decision SR-110): a HELLO or TIME that the wide search
 * could not open is tried against the next ATALAIA_DEEP_SLICE epochs of the whole range above it, a
 * slice per search the budget above allows, the source's cursor moving on and wrapping, so a box
 * that took a random high epoch after losing its epoch store (SR-27), or a controller that did
 * (SR-29), is found within a minute or two (65536 / 2048 slices of one search every 2 s at most)
 * without any controller's help. The slice is the cost of one search: about 60 ms of decryptions.
 */
#define ATALAIA_DEEP_SLICE 2048

/* ---- Radio protocol state ------------------------------------------------- */

typedef struct {
    uint16_t game_id;
    uint16_t node_id;
    uint16_t epoch;
    uint16_t seq;
    uint8_t game_key[ATALAIA_RF_KEY_SIZE];
    uint8_t epoch_tag[ATALAIA_EPOCH_TAG_SIZE]; /* the key's tag in the epoch store */
    bool has_key;
    bool tx_blocked;
    bool epoch_lost; /* the last boot_epoch found the epoch store without this key (SR-27) */
    const atalaia_crypto_ops_t *crypto;
    const atalaia_radio_nvs_ops_t *nvs;
    uint8_t max_hops; /* hop_limit of our packets and relay clamp (ADR-P2-6); 2 by default */

    /* Where packets go: NULL = radio_task_send(). The host box and the tests set their own. */
    bool (*tx)(void *ctx, const uint8_t *pkt, size_t len);
    void *tx_ctx;

    /* Per-source epoch table for receiver-side epoch trial. */
    atalaia_radio_source_epoch_t source_epochs[RADIO_PROTO_MAX_SOURCES];

    /* The wide search's budget (see ATALAIA_WIDE_GAP_MS). */
    struct {
        uint16_t source;
        uint32_t ms;
        uint32_t
            deep_next; /* the next epoch the deep search tries for this source (0: not started) */
        bool valid;
    } wide_recent[ATALAIA_WIDE_SOURCES];
    uint32_t wide_ms[ATALAIA_WIDE_PER_MIN];
    bool wide_set[ATALAIA_WIDE_PER_MIN];
    uint8_t wide_next;
    uint32_t wide_searches; /* wide searches made */
    uint32_t wide_refused;  /* wide searches the budget refused */
    uint32_t deep_searches; /* deep slices tried (SR-110) */
    uint32_t deep_found;    /* sources a deep slice found at a far higher epoch */

    /* Authenticated packets the replay window refused (RFC 0001 Amendment 23). last_replay is the
     * verdict of the latest on_recv_window call that authenticated a packet: the caller tells a
     * flood copy (DUPLICATE) from a packet too old to be genuine (TOO_OLD) by it. */
    atalaia_replay_verdict_t last_replay;
    uint32_t replay_duplicates;
    uint32_t replay_too_old;
} atalaia_radio_proto_t;

/*
 * Initialise the radio protocol layer.
 * nvs may be NULL (NVS disabled; epoch starts at 0, no persistence).
 */
void atalaia_radio_proto_init(atalaia_radio_proto_t *rp, uint16_t game_id, uint16_t node_id,
                              const atalaia_crypto_ops_t *crypto,
                              const atalaia_radio_nvs_ops_t *nvs);

/*
 * Boot-time epoch cycle for the game key (set_key first): this key's stored
 * epoch + 1, or 1 for a key the store does not know; persisted before the
 * first TX. resuming: the box rejoins its stored game after a reboot, so an
 * epoch from the firmware before the per-key store (read_legacy_epoch) is this
 * key's and goes on from there; otherwise it is ignored. Returns false (and
 * sets tx_blocked) without a key, on a store read or write error, an
 * unreadable store, or epoch 65535 already used. nvs NULL: no-op, true.
 */
bool atalaia_radio_proto_boot_epoch(atalaia_radio_proto_t *rp, bool resuming);

/*
 * True if the store knows this key only as retired (an old game's: its epochs
 * are no longer known, so it must not transmit again; the join is refused).
 * False for a key with a record, a new key, no store or an unreadable one.
 */
bool atalaia_radio_epoch_key_retired(const atalaia_radio_nvs_ops_t *nvs,
                                     const uint8_t key[ATALAIA_RF_KEY_SIZE]);

/* The key's tag in the epoch store: the first 8 bytes of
 * HMAC-SHA256(key, "atalaia epoch tag") (RFC 0001 amendment of 2026-10-22). */
void atalaia_radio_epoch_tag(const uint8_t key[ATALAIA_RF_KEY_SIZE],
                             uint8_t tag[ATALAIA_EPOCH_TAG_SIZE]);

/*
 * A box that resumes its stored game but has no epoch record for its key lost its store (NVS
 * erased or replaced; every game it joins afresh has a record from its first packet on). Its
 * epoch there starts at a random value in [ATALAIA_EPOCH_LOST_MIN, ATALAIA_EPOCH_LOST_MAX], not at
 * 1: epochs 1.. may all have been used with this key by the box's earlier life, and a nonce used
 * twice under one key breaks AES-CCM (decision SR-27, FLD-10). The floor is far above any epoch a
 * game reaches (a reboot or a 65536-packet wrap each add one); the ceiling leaves 4096 epochs
 * before the space ends. No receiver that knew the box looks that far, so it is heard again only
 * once it is found: by the receivers' deep search of its HELLO (ATALAIA_DEEP_SLICE, decision
 * SR-110), or at once when a controller names its epoch (SET_PEER_EPOCH, CMD peer).
 */
#define ATALAIA_EPOCH_LOST_MIN 4096u
#define ATALAIA_EPOCH_LOST_MAX 61439u

/* Packets a (re)started node sends first (HELLO, TIME) are searched this many
 * epochs above the source's last one: a box that rebooted in a crash loop is
 * heard again (decision BN-8), within the wide search budget (BN-20). Lower
 * epochs are still never tried. */
#define ATALAIA_RESTART_EPOCH_WINDOW 256

/* Set the game key (from NFC tap or NVS restore). */
void atalaia_radio_proto_set_key(atalaia_radio_proto_t *rp, const uint8_t key[ATALAIA_RF_KEY_SIZE]);

/* Set the epoch (for testing or manual resync). */
void atalaia_radio_proto_set_epoch(atalaia_radio_proto_t *rp, uint16_t epoch);

/*
 * Set a source's epoch in the receiver table (resync from HELLO/STATE; a controller's
 * SET_PEER_EPOCH and a CMD peer). It only ever goes up (decision SR-111): an epoch at or below the
 * one the table has is ignored (an equal one only makes the source trusted), so a stale or replayed
 * announcement cannot make a receiver refuse a source it hears. Returns true when the table moved.
 */
bool atalaia_radio_proto_set_source_epoch(atalaia_radio_proto_t *rp, uint16_t source,
                                          uint16_t epoch);

/*
 * Encrypt payload as one packet (header seq = the next seq, our epoch,
 * hop_limit = max_hops) and hand it to the TX sink. *seq_out, if not NULL,
 * receives the header seq used. Returns false if tx_blocked, there is no
 * key, the payload is too long, the seq/epoch cannot advance safely, or the
 * sink refused the packet (the seq is used up either way).
 */
bool atalaia_radio_proto_send_payload(atalaia_radio_proto_t *rp, uint8_t msg_type, uint8_t prio,
                                      bool ack_req, const uint8_t *payload, size_t len,
                                      uint16_t *seq_out);

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

/*
 * Like atalaia_radio_proto_on_recv, but searches up to `window` epochs
 * above the source's last known epoch (or epochs 0..window for an unknown
 * source) instead of only one. Never tries a lower epoch, so replays of
 * older epochs are still rejected. window = 1 is exactly on_recv. HELLO
 * and TIME packets (and a provisional source's) are then searched up to
 * ATALAIA_RESTART_EPOCH_WINDOW above, within the budget (rx_msg->timestamp_ms
 * is the clock).
 *
 * The USB modem uses a wider window (CONFIG_ATALAIA_MODEM_EPOCH_WINDOW):
 * a box that rebooted twice while out of range, or that joined with an
 * epoch above 1, would otherwise never be decrypted again. If out_epoch
 * is not NULL it receives the epoch that authenticated the packet.
 */
bool atalaia_radio_proto_on_recv_window(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx_msg,
                                        uint16_t window, atalaia_header_t *out_hdr,
                                        uint8_t *out_payload, size_t *out_payload_len,
                                        uint16_t *out_epoch);

#endif /* ATALAIA_RADIO_PROTOCOL_H */
