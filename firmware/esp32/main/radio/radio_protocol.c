/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Radio protocol glue: encodes/decodes Skirmesh-RF packets.
 * Owns epoch persistence and per-source epoch trial on receive.
 */
#include "radio_protocol.h"

#include <string.h>

#include "atalaia/join.h" /* atalaia_hmac_sha256 */

/* ---- Helpers -------------------------------------------------------------- */

static bool store_epoch(atalaia_radio_proto_t *rp, uint16_t epoch, bool resuming);

/*
 * Advance the sequence counter.  When it wraps from 65535 to 0,
 * increment the epoch and persist it via NVS.  If NVS write fails or
 * the epoch is exhausted, set tx_blocked.
 * Returns true if the sequence (and epoch, if wrapped) advanced safely.
 */
static bool advance_seq(atalaia_radio_proto_t *rp)
{
    uint16_t old_seq = rp->seq;
    rp->seq = (uint16_t)(old_seq + 1);
    if (rp->seq == 0) {
        /* Sequence wrapped: need a new epoch. */
        if (rp->epoch == 65535) {
            rp->tx_blocked = true;
            return false;
        }
        rp->epoch++;
        if (rp->nvs != NULL && !store_epoch(rp, rp->epoch, false)) {
            rp->tx_blocked = true;
            return false;
        }
    }
    return true;
}

/*
 * Look up a source in the per-source epoch table.
 * Returns the index, or -1 if not found.
 */
static int find_source(const atalaia_radio_proto_t *rp, uint16_t source)
{
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES; i++) {
        if (rp->source_epochs[i].valid && rp->source_epochs[i].source == source) {
            return i;
        }
    }
    return -1;
}

/*
 * Find a free slot in the source epoch table, or evict the first entry
 * (simple circular eviction).
 */
static int alloc_source_slot(atalaia_radio_proto_t *rp)
{
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES; i++) {
        if (!rp->source_epochs[i].valid) return i;
    }
    /* Table full: evict slot 0 (oldest by insertion order). */
    /* Shift everything down by one to keep a rough FIFO order. */
    for (int i = 0; i < RADIO_PROTO_MAX_SOURCES - 1; i++) {
        rp->source_epochs[i] = rp->source_epochs[i + 1];
    }
    rp->source_epochs[RADIO_PROTO_MAX_SOURCES - 1].valid = false;
    return RADIO_PROTO_MAX_SOURCES - 1;
}

/* ---- Public API ----------------------------------------------------------- */

void atalaia_radio_proto_init(atalaia_radio_proto_t *rp, uint16_t game_id, uint16_t node_id,
                              const atalaia_crypto_ops_t *crypto,
                              const atalaia_radio_nvs_ops_t *nvs)
{
    memset(rp, 0, sizeof(*rp));
    rp->game_id = game_id;
    rp->node_id = node_id;
    rp->crypto = crypto;
    rp->nvs = nvs;
    rp->epoch = 0;
    rp->seq = 0;
    rp->has_key = false;
    rp->tx_blocked = false;
    rp->max_hops = 2;
    rp->tx = NULL;
    rp->tx_ctx = NULL;
}

void atalaia_radio_epoch_tag(const uint8_t key[ATALAIA_RF_KEY_SIZE],
                             uint8_t tag[ATALAIA_EPOCH_TAG_SIZE])
{
    static const char label[] = "atalaia epoch tag";
    uint8_t mac[32];
    atalaia_hmac_sha256(key, ATALAIA_RF_KEY_SIZE, (const uint8_t *)label, sizeof(label) - 1, mac);
    memcpy(tag, mac, ATALAIA_EPOCH_TAG_SIZE);
    memset(mac, 0, sizeof(mac));
}

/* The epoch store, decoded (radio_protocol.h). */
typedef struct {
    uint8_t count;
    uint8_t retired_count;
    uint8_t tag[ATALAIA_EPOCH_KEYS][ATALAIA_EPOCH_TAG_SIZE];
    uint16_t epoch[ATALAIA_EPOCH_KEYS];
    uint8_t retired[ATALAIA_EPOCH_RETIRED][ATALAIA_EPOCH_TAG_SIZE];
} epoch_store_t;

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)(p[0] << 8 | p[1]);
}

/* Decodes a blob of version 1 (no retired tags) or 2. False if it is malformed. */
static bool parse_store(const uint8_t *buf, size_t n, epoch_store_t *st)
{
    memset(st, 0, sizeof(*st));
    size_t head;
    if (n >= 2 && buf[0] == 1) {
        head = 2;
        if (buf[1] > 8) return false; /* version 1 kept 8 keys */
    } else if (n >= 4 && buf[0] == ATALAIA_EPOCH_STORE_VER && buf[3] == 0) {
        head = 4;
        if (buf[2] > ATALAIA_EPOCH_RETIRED) return false;
        st->retired_count = buf[2];
    } else {
        return false;
    }
    if (buf[1] > ATALAIA_EPOCH_KEYS ||
        n != head + (size_t)buf[1] * ATALAIA_EPOCH_REC_SIZE +
                 (size_t)st->retired_count * ATALAIA_EPOCH_TAG_SIZE) {
        return false;
    }
    st->count = buf[1];
    const uint8_t *r = buf + head;
    for (uint8_t i = 0; i < st->count; i++, r += ATALAIA_EPOCH_REC_SIZE) {
        memcpy(st->tag[i], r, ATALAIA_EPOCH_TAG_SIZE);
        st->epoch[i] = be16(r + ATALAIA_EPOCH_TAG_SIZE);
    }
    for (uint8_t i = 0; i < st->retired_count; i++, r += ATALAIA_EPOCH_TAG_SIZE) {
        memcpy(st->retired[i], r, ATALAIA_EPOCH_TAG_SIZE);
    }
    return true;
}

static int store_find(const epoch_store_t *st, const uint8_t tag[ATALAIA_EPOCH_TAG_SIZE])
{
    for (int i = 0; i < st->count; i++) {
        if (memcmp(st->tag[i], tag, ATALAIA_EPOCH_TAG_SIZE) == 0) return i;
    }
    return -1;
}

static bool store_retired(const epoch_store_t *st, const uint8_t tag[ATALAIA_EPOCH_TAG_SIZE])
{
    for (int i = 0; i < st->retired_count; i++) {
        if (memcmp(st->retired[i], tag, ATALAIA_EPOCH_TAG_SIZE) == 0) return true;
    }
    return false;
}

/* Puts (tag, epoch) first. A full store retires its oldest record's key (its tag alone is kept,
 * the oldest retired tag goes). */
static void store_put(epoch_store_t *st, const uint8_t tag[ATALAIA_EPOCH_TAG_SIZE], uint16_t epoch)
{
    int at = store_find(st, tag);
    if (at < 0 && st->count == ATALAIA_EPOCH_KEYS) {
        at = st->count - 1;
        int keep =
            st->retired_count < ATALAIA_EPOCH_RETIRED ? st->retired_count : st->retired_count - 1;
        memmove(st->retired[1], st->retired[0], (size_t)keep * ATALAIA_EPOCH_TAG_SIZE);
        memcpy(st->retired[0], st->tag[at], ATALAIA_EPOCH_TAG_SIZE);
        st->retired_count = (uint8_t)(keep + 1);
    }
    if (at < 0) at = st->count++;
    for (int i = at; i > 0; i--) {
        memcpy(st->tag[i], st->tag[i - 1], ATALAIA_EPOCH_TAG_SIZE);
        st->epoch[i] = st->epoch[i - 1];
    }
    memcpy(st->tag[0], tag, ATALAIA_EPOCH_TAG_SIZE);
    st->epoch[0] = epoch;
}

/* Reads the store through nvs (an absent store is an empty one); false if unreadable. */
static bool read_store(const atalaia_radio_nvs_ops_t *nvs, epoch_store_t *st, bool *absent)
{
    static uint8_t buf[ATALAIA_EPOCH_STORE_MAX]; /* static: 600 bytes, off the game task's stack */
    int n = nvs->read_epochs(nvs->ctx, buf, sizeof(buf));
    *absent = n == -1;
    if (n == -1) {
        memset(st, 0, sizeof(*st));
        return true;
    }
    return n >= 0 && parse_store(buf, (size_t)n, st);
}

/*
 * Reads the epoch store. Resuming with no store yet: the firmware before the amendment kept one
 * u16 for every key; it belongs to the stored game the box resumes, and to no new game, so it
 * becomes this key's record. False on a read error or a malformed blob: the radio must not
 * guess an epoch.
 */
static bool load_store(atalaia_radio_proto_t *rp, epoch_store_t *st, bool resuming)
{
    bool absent = false;
    if (!read_store(rp->nvs, st, &absent)) return false;
    if (absent && resuming && rp->nvs->read_legacy_epoch != NULL) {
        uint16_t legacy = 0;
        int rc = rp->nvs->read_legacy_epoch(rp->nvs->ctx, &legacy);
        if (rc == -2) return false;
        if (rc == 0) store_put(st, rp->epoch_tag, legacy);
    }
    return true;
}

/* Writes the whole store in one atomic write. */
static bool save_store(atalaia_radio_proto_t *rp, const epoch_store_t *st)
{
    static uint8_t out[ATALAIA_EPOCH_STORE_MAX];
    out[0] = ATALAIA_EPOCH_STORE_VER;
    out[1] = st->count;
    out[2] = st->retired_count;
    out[3] = 0;
    uint8_t *w = out + 4;
    for (uint8_t i = 0; i < st->count; i++, w += ATALAIA_EPOCH_REC_SIZE) {
        memcpy(w, st->tag[i], ATALAIA_EPOCH_TAG_SIZE);
        w[ATALAIA_EPOCH_TAG_SIZE] = (uint8_t)(st->epoch[i] >> 8);
        w[ATALAIA_EPOCH_TAG_SIZE + 1] = (uint8_t)st->epoch[i];
    }
    for (uint8_t i = 0; i < st->retired_count; i++, w += ATALAIA_EPOCH_TAG_SIZE) {
        memcpy(w, st->retired[i], ATALAIA_EPOCH_TAG_SIZE);
    }
    return rp->nvs->write_epochs(rp->nvs->ctx, out, (size_t)(w - out)) == 0;
}

bool atalaia_radio_epoch_key_retired(const atalaia_radio_nvs_ops_t *nvs,
                                     const uint8_t key[ATALAIA_RF_KEY_SIZE])
{
    if (nvs == NULL) return false;
    static epoch_store_t st;
    bool absent = false;
    if (!read_store(nvs, &st, &absent)) return false;
    uint8_t tag[ATALAIA_EPOCH_TAG_SIZE];
    atalaia_radio_epoch_tag(key, tag);
    return store_find(&st, tag) < 0 && store_retired(&st, tag);
}

/* Stores epoch as this key's (seq wrap). The store is read again, so it never goes back. */
static bool store_epoch(atalaia_radio_proto_t *rp, uint16_t epoch, bool resuming)
{
    static epoch_store_t st;
    if (!load_store(rp, &st, resuming)) return false;
    int at = store_find(&st, rp->epoch_tag);
    if (at >= 0 && st.epoch[at] >= epoch) return false; /* never store a lower or equal epoch */
    if (at < 0 && store_retired(&st, rp->epoch_tag)) return false;
    store_put(&st, rp->epoch_tag, epoch);
    return save_store(rp, &st);
}

bool atalaia_radio_proto_boot_epoch(atalaia_radio_proto_t *rp, bool resuming)
{
    if (rp->nvs == NULL) return true;
    if (!rp->has_key) {
        rp->tx_blocked = true;
        return false;
    }

    static epoch_store_t st; /* static: ~600 bytes, off the game task's stack */
    if (!load_store(rp, &st, resuming)) {
        rp->tx_blocked = true;
        return false;
    }
    /* This key's next epoch: a reboot or rejoin goes on above every epoch it used; a new key
     * starts at 1 (every game has a fresh random key: nonces are unique per key, and a
     * receiver meets a new source from epoch 0). A retired key's epochs are no longer known:
     * starting it again could reuse a nonce, so it does not transmit (BN-19). */
    int at = store_find(&st, rp->epoch_tag);
    if ((at >= 0 && st.epoch[at] == 65535) || (at < 0 && store_retired(&st, rp->epoch_tag))) {
        rp->tx_blocked = true;
        return false;
    }
    uint16_t new_epoch = at >= 0 ? (uint16_t)(st.epoch[at] + 1) : 1;

    /* Persist BEFORE first TX. */
    store_put(&st, rp->epoch_tag, new_epoch);
    if (!save_store(rp, &st)) {
        rp->tx_blocked = true;
        return false;
    }

    rp->epoch = new_epoch;
    rp->seq = 0;
    return true;
}

void atalaia_radio_proto_set_key(atalaia_radio_proto_t *rp, const uint8_t key[ATALAIA_RF_KEY_SIZE])
{
    memcpy(rp->game_key, key, ATALAIA_RF_KEY_SIZE);
    atalaia_radio_epoch_tag(key, rp->epoch_tag);
    rp->has_key = true;
}

void atalaia_radio_proto_set_epoch(atalaia_radio_proto_t *rp, uint16_t epoch)
{
    rp->epoch = epoch;
    /* Reset sequence on epoch change for nonce safety. */
    rp->seq = 0;
}

void atalaia_radio_proto_set_source_epoch(atalaia_radio_proto_t *rp, uint16_t source,
                                          uint16_t epoch)
{
    int idx = find_source(rp, source);
    if (idx < 0) {
        idx = alloc_source_slot(rp);
    }
    rp->source_epochs[idx].source = source;
    rp->source_epochs[idx].epoch = epoch;
    rp->source_epochs[idx].valid = true;
    rp->source_epochs[idx].provisional = false; /* told by the controller: trusted */
}

bool atalaia_radio_proto_send_payload(atalaia_radio_proto_t *rp, uint8_t msg_type, uint8_t prio,
                                      bool ack_req, const uint8_t *payload, size_t len,
                                      uint16_t *seq_out)
{
    if (!rp->has_key) return false;
    if (rp->tx_blocked) return false;
    if (len > ATALAIA_RF_PAYLOAD_MAX) return false;

    atalaia_header_t hdr;
    hdr.version_flags = ATALAIA_VF_MAKE(1, prio, ack_req ? 1 : 0, 1);
    hdr.game_id = rp->game_id;
    hdr.source = rp->node_id;
    hdr.seq = rp->seq;
    hdr.hop_limit = rp->max_hops;
    hdr.type = msg_type;

    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, rp->epoch, rp->game_key, payload, len, pkt,
                                            sizeof(pkt), rp->crypto);
    if (pkt_len == 0) return false;

    /* The nonce (epoch, seq) is used: advance before the packet can leave. */
    if (!advance_seq(rp)) return false;
    if (seq_out != NULL) *seq_out = hdr.seq;

    if (rp->tx != NULL) return rp->tx(rp->tx_ctx, pkt, pkt_len);
    return radio_task_send(pkt, pkt_len);
}

bool atalaia_radio_proto_send_event(atalaia_radio_proto_t *rp, const atalaia_event_t *ev,
                                    const char *data_json)
{
    if (!rp->has_key) return false;
    if (rp->tx_blocked) return false;

    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t payload_len = atalaia_event_encode(ev, data_json, payload, sizeof(payload), NULL);
    if (payload_len == 0) return false;

    /* Normal and critical events ask for an ACK; telemetry is best effort. */
    return atalaia_radio_proto_send_payload(rp, ATALAIA_MSG_EVENT, (uint8_t)ev->prio,
                                            ev->prio != ATALAIA_PRIO_TELEMETRY, payload,
                                            payload_len, NULL);
}

bool atalaia_radio_proto_send_state(atalaia_radio_proto_t *rp, const atalaia_state_msg_t *state)
{
    if (!rp->has_key) return false;
    if (rp->tx_blocked) return false;

    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t payload_len = atalaia_state_encode(state, payload, sizeof(payload));
    if (payload_len == 0) return false;

    return atalaia_radio_proto_send_payload(rp, ATALAIA_MSG_STATE, 0, false, payload, payload_len,
                                            NULL);
}

bool atalaia_radio_proto_on_recv(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx_msg,
                                 atalaia_header_t *out_hdr, uint8_t *out_payload,
                                 size_t *out_payload_len)
{
    return atalaia_radio_proto_on_recv_window(rp, rx_msg, 1, out_hdr, out_payload, out_payload_len,
                                              NULL);
}

/* Tries epochs first..last (clamped to 65535); the one that authenticates in *found. */
static bool try_epochs(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx, uint32_t first,
                       uint32_t last, atalaia_header_t *out_hdr, uint8_t *out_payload,
                       size_t *out_payload_len, uint16_t *found)
{
    if (last > 65535u) last = 65535u;
    for (uint32_t e = first; e <= last; e++) {
        if (atalaia_packet_decrypt(rx->data, rx->len, (uint16_t)e, rp->game_key, out_hdr,
                                   out_payload, out_payload_len, rp->crypto)) {
            *found = (uint16_t)e;
            return true;
        }
    }
    return false;
}

/* May a wide search run now for source? Spends the budget when it may. */
static bool wide_allowed(atalaia_radio_proto_t *rp, uint16_t source, uint32_t now)
{
    int slot = -1;
    for (int i = 0; i < ATALAIA_WIDE_SOURCES; i++) {
        if (rp->wide_recent[i].valid && rp->wide_recent[i].source == source) {
            if (now - rp->wide_recent[i].ms < ATALAIA_WIDE_GAP_MS) return false;
            slot = i;
        }
    }
    uint8_t g = rp->wide_next;
    if (rp->wide_set[g] && now - rp->wide_ms[g] < 60000u) return false; /* the minute's budget */
    if (slot < 0) {
        /* A free entry, else the one searched longest ago. */
        slot = 0;
        for (int i = 0; i < ATALAIA_WIDE_SOURCES; i++) {
            if (!rp->wide_recent[i].valid) {
                slot = i;
                break;
            }
            if (now - rp->wide_recent[i].ms > now - rp->wide_recent[slot].ms) slot = i;
        }
    }
    rp->wide_recent[slot].source = source;
    rp->wide_recent[slot].ms = now;
    rp->wide_recent[slot].valid = true;
    rp->wide_ms[g] = now;
    rp->wide_set[g] = true;
    rp->wide_next = (uint8_t)((g + 1u) % ATALAIA_WIDE_PER_MIN);
    return true;
}

bool atalaia_radio_proto_on_recv_window(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx_msg,
                                        uint16_t window, atalaia_header_t *out_hdr,
                                        uint8_t *out_payload, size_t *out_payload_len,
                                        uint16_t *out_epoch)
{
    if (!rp->has_key) return false;
    if (rx_msg->len < ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE) {
        return false;
    }
    if (window == 0) window = 1;

    /* Decode the cleartext header first to get the source. */
    atalaia_header_t hdr;
    if (!atalaia_header_decode(rx_msg->data, &hdr)) return false;
    uint16_t source = hdr.source;

    /* Start at the source's last known epoch, or at 0 for a new source, and try at most
     * `window` epochs above it: never a lower epoch (ADR-P2-2). */
    int idx = find_source(rp, source);
    uint16_t first = idx >= 0 ? rp->source_epochs[idx].epoch : 0;
    uint16_t epoch = 0;
    bool provisional = idx < 0; /* a source met for the first time (BN-21) */
    bool ok = try_epochs(rp, rx_msg, first, (uint32_t)first + window, out_hdr, out_payload,
                         out_payload_len, &epoch);
    if (ok && idx >= 0 && rp->source_epochs[idx].provisional) {
        provisional = false; /* a second packet in the normal window confirms the source */
    }
    if (!ok) {
        /* What a node sends first after a (re)start is searched further up, so a box that
         * rebooted in a crash loop is heard again (BN-8); and so is anything from a source
         * whose epoch may be an old recording's (BN-21). Never below, and within the budget
         * (BN-20). The type is in the AAD: a packet whose type was changed does not open. */
        bool wide_type = hdr.type == ATALAIA_MSG_HELLO || hdr.type == ATALAIA_MSG_TIME ||
                         (idx >= 0 && rp->source_epochs[idx].provisional);
        if (!wide_type || window >= ATALAIA_RESTART_EPOCH_WINDOW) return false;
        if (!wide_allowed(rp, source, rx_msg->timestamp_ms)) {
            rp->wide_refused++;
            return false;
        }
        rp->wide_searches++;
        ok = try_epochs(rp, rx_msg, (uint32_t)first + window + 1u,
                        (uint32_t)first + ATALAIA_RESTART_EPOCH_WINDOW, out_hdr, out_payload,
                        out_payload_len, &epoch);
        if (!ok) return false;
        if (idx >= 0) provisional = rp->source_epochs[idx].provisional;
    }
    /* Authenticated: remember (or adopt) this epoch for the source. */
    if (idx < 0) {
        idx = alloc_source_slot(rp);
    }
    rp->source_epochs[idx].source = source;
    rp->source_epochs[idx].epoch = epoch;
    rp->source_epochs[idx].valid = true;
    rp->source_epochs[idx].provisional = provisional;
    if (out_epoch != NULL) *out_epoch = epoch;
    return true;
}
