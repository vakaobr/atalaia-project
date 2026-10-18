/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Radio protocol glue: encodes/decodes Skirmesh-RF packets.
 * Owns epoch persistence and per-source epoch trial on receive.
 */
#include "radio_protocol.h"

#include <string.h>

/* ---- Helpers -------------------------------------------------------------- */

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
        if (rp->nvs != NULL) {
            if (rp->nvs->write_epoch(rp->nvs->ctx, rp->epoch) != 0) {
                rp->tx_blocked = true;
                return false;
            }
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
}

bool atalaia_radio_proto_boot_epoch(atalaia_radio_proto_t *rp)
{
    if (rp->nvs == NULL) return true;

    uint16_t stored = 0;
    int rc = rp->nvs->read_epoch(rp->nvs->ctx, &stored);
    if (rc == -2) {
        /* NVS read error. */
        rp->tx_blocked = true;
        return false;
    }
    if (rc == -1) {
        /* Not found: first boot, epoch starts at 0. */
        stored = 0;
    }

    /* Increment to guarantee a fresh epoch after every reboot. */
    if (stored == 65535) {
        rp->tx_blocked = true;
        return false;
    }
    uint16_t new_epoch = (uint16_t)(stored + 1);

    /* Persist BEFORE first TX. */
    if (rp->nvs->write_epoch(rp->nvs->ctx, new_epoch) != 0) {
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
}

bool atalaia_radio_proto_send_event(atalaia_radio_proto_t *rp, const atalaia_event_t *ev,
                                    const char *data_json)
{
    if (!rp->has_key) return false;
    if (rp->tx_blocked) return false;

    /* Encode the event payload. */
    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t payload_len = atalaia_event_encode(ev, data_json, payload, sizeof(payload), NULL);
    if (payload_len == 0) return false;

    /* Build the header. */
    atalaia_header_t hdr;
    hdr.version_flags = ATALAIA_VF_MAKE(1, ev->prio, 1, 1);
    hdr.game_id = rp->game_id;
    hdr.source = rp->node_id;
    hdr.seq = rp->seq;
    hdr.hop_limit = 3;
    hdr.type = ATALAIA_MSG_EVENT;

    /* Encrypt and send. */
    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, rp->epoch, rp->game_key, payload, payload_len,
                                            pkt, sizeof(pkt), rp->crypto);
    if (pkt_len == 0) return false;

    if (!advance_seq(rp)) return false;

    return radio_task_send(pkt, pkt_len);
}

bool atalaia_radio_proto_send_state(atalaia_radio_proto_t *rp, const atalaia_state_msg_t *state)
{
    if (!rp->has_key) return false;
    if (rp->tx_blocked) return false;

    uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
    size_t payload_len = atalaia_state_encode(state, payload, sizeof(payload));
    if (payload_len == 0) return false;

    atalaia_header_t hdr;
    hdr.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1);
    hdr.game_id = rp->game_id;
    hdr.source = rp->node_id;
    hdr.seq = rp->seq;
    hdr.hop_limit = 1;
    hdr.type = ATALAIA_MSG_STATE;

    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, rp->epoch, rp->game_key, payload, payload_len,
                                            pkt, sizeof(pkt), rp->crypto);
    if (pkt_len == 0) return false;

    if (!advance_seq(rp)) return false;

    return radio_task_send(pkt, pkt_len);
}

bool atalaia_radio_proto_on_recv(atalaia_radio_proto_t *rp, const radio_rx_msg_t *rx_msg,
                                 atalaia_header_t *out_hdr, uint8_t *out_payload,
                                 size_t *out_payload_len)
{
    if (!rp->has_key) return false;
    if (rx_msg->len < ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE) {
        return false;
    }

    /* Decode the cleartext header first to get the source. */
    atalaia_header_t hdr;
    if (!atalaia_header_decode(rx_msg->data, &hdr)) return false;

    uint16_t source = hdr.source;

    /* Look up the source's last known epoch. */
    int idx = find_source(rp, source);
    uint16_t try_epoch;
    bool source_known;

    if (idx >= 0) {
        try_epoch = rp->source_epochs[idx].epoch;
        source_known = true;
    } else {
        /* Unknown source: try epoch 0 first, then 1. */
        try_epoch = 0;
        source_known = false;
    }

    /* Try decryption with the source's current epoch. */
    if (atalaia_packet_decrypt(rx_msg->data, rx_msg->len, try_epoch, rp->game_key, out_hdr,
                               out_payload, out_payload_len, rp->crypto)) {
        /* Success at the current epoch. */
        if (!source_known) {
            /* Add to the table. */
            int slot = alloc_source_slot(rp);
            rp->source_epochs[slot].source = source;
            rp->source_epochs[slot].epoch = try_epoch;
            rp->source_epochs[slot].valid = true;
        }
        return true;
    }

    /* Try epoch+1 (sender rebooted or wrapped). */
    if (try_epoch < 65535) {
        uint16_t next_epoch = (uint16_t)(try_epoch + 1);
        if (atalaia_packet_decrypt(rx_msg->data, rx_msg->len, next_epoch, rp->game_key, out_hdr,
                                   out_payload, out_payload_len, rp->crypto)) {
            /* Adopt the new epoch. */
            if (idx >= 0) {
                rp->source_epochs[idx].epoch = next_epoch;
            } else {
                int slot = alloc_source_slot(rp);
                rp->source_epochs[slot].source = source;
                rp->source_epochs[slot].epoch = next_epoch;
                rp->source_epochs[slot].valid = true;
            }
            return true;
        }
    }

    /* For unknown sources, also try epoch 1 if we started at 0. */
    if (!source_known && try_epoch == 0) {
        /* Already tried 0 and 1 (0+1=1), so nothing more to do. */
    }

    /* Both attempts failed. */
    return false;
}
