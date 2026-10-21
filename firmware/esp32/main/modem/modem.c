/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem logic. See modem.h and protocol/usb-modem.md.
 */
#include "modem.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/duty_cycle.h"
#include "atalaia/version.h"

/* ---- Output frames -------------------------------------------------------- */

static void send_frame(modem_t *m, uint8_t type, const uint8_t *payload, size_t len)
{
    if (m->io.frame_out != NULL) {
        m->io.frame_out(m->io.frame_ctx, type, payload, len);
        return;
    }
    uint8_t buf[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(type, payload, len, buf, sizeof(buf));
    if (n > 0 && m->io.serial_write != NULL) {
        m->io.serial_write(m->io.ctx, buf, n);
    }
}

static void send_error(modem_t *m, modem_error_t code, const char *message)
{
    uint8_t buf[64];
    size_t len = strlen(message);
    if (len > sizeof(buf) - 1) len = sizeof(buf) - 1;
    buf[0] = (uint8_t)code;
    memcpy(buf + 1, message, len);
    if (code == MODEM_ERR_BAD_FRAME) {
        m->count.bad_frames++;
    }
    send_frame(m, MODEM_FRAME_ERROR, buf, len + 1);
}

static void send_tx_ack(modem_t *m, uint16_t seq, modem_tx_status_t status)
{
    uint8_t buf[3] = {(uint8_t)(seq >> 8), (uint8_t)(seq & 0xFF), (uint8_t)status};
    send_frame(m, MODEM_FRAME_TX_ACK, buf, sizeof(buf));
}

static uint32_t now(const modem_t *m)
{
    return m->io.now_ms != NULL ? m->io.now_ms(m->io.ctx) : 0;
}

/* STATUS: a compact JSON object, the reply to every command. */
static void send_status(modem_t *m, int cmd, bool has_token, uint32_t token)
{
    char json[MODEM_FRAME_PAYLOAD_MAX];
    uint32_t duty = 0;
    if (m->radio_present && m->io.duty_cycle_remaining_ms != NULL) {
        duty = m->io.duty_cycle_remaining_ms(m->io.ctx);
    }
    int n = snprintf(json, sizeof(json),
                     "{\"cmd\":%d,\"configured\":%s,\"radio\":%s,\"game_id\":%u,\"channel_hz\":%lu,"
                     "\"duty_ms\":%lu,\"uptime_s\":%lu,\"rx\":%lu,\"rx_auth_fail\":%lu,"
                     "\"tx\":%lu,\"tx_fail\":%lu,\"measuring\":%s",
                     cmd, m->configured ? "true" : "false", m->radio_present ? "true" : "false",
                     (unsigned)m->game_id, (unsigned long)m->channel_hz, (unsigned long)duty,
                     (unsigned long)((now(m) - m->boot_ms) / 1000u), (unsigned long)m->count.rx_ok,
                     (unsigned long)m->count.rx_auth_fail, (unsigned long)m->count.tx_ok,
                     (unsigned long)m->count.tx_fail, m->measuring ? "true" : "false");
    if (n < 0 || (size_t)n >= sizeof(json) - 24) {
        return;
    }
    if (has_token) {
        n += snprintf(json + n, sizeof(json) - (size_t)n, ",\"ping\":%lu", (unsigned long)token);
    }
    json[n++] = '}';
    send_frame(m, MODEM_FRAME_STATUS, (const uint8_t *)json, (size_t)n);
}

void modem_send_ident(modem_t *m)
{
    char json[MODEM_FRAME_PAYLOAD_MAX];
    int n = snprintf(json, sizeof(json),
                     "{\"fw\":\"atalaia-modem\",\"fw_version\":\"%s\",\"core_version\":\"%s\","
                     "\"framing\":%d,\"radio\":\"%s\",\"payload_max\":%d,\"epoch_window\":%u,"
                     "\"measure\":%s,\"field\":true}",
                     m->fw_version != NULL ? m->fw_version : "unknown", atalaia_version(),
                     MODEM_PROTOCOL_VERSION, m->radio_present ? "sx1262" : "none",
                     ATALAIA_RF_PAYLOAD_MAX, (unsigned)m->epoch_window,
                     m->radio_present && m->io.measure_start != NULL ? "true" : "false");
    if (n > 0 && (size_t)n < sizeof(json)) {
        send_frame(m, MODEM_FRAME_IDENT, (const uint8_t *)json, (size_t)n);
    }
}

/* ---- Helpers -------------------------------------------------------------- */

static uint16_t be16(const uint8_t *p)
{
    return (uint16_t)(((uint16_t)p[0] << 8) | p[1]);
}

static uint32_t be32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}

static bool apply_channel(modem_t *m, uint32_t hz)
{
    /* The whole 125 kHz channel inside one EU868 sub-band (RFC 0001 Amendment 3). */
    if (!atalaia_channel_ok(hz)) {
        send_error(m, MODEM_ERR_BAD_PARAMS, "channel does not fit in an EU868 sub-band");
        return false;
    }
    if (m->radio_present && m->io.set_channel != NULL && m->io.set_channel(m->io.ctx, hz) != 0) {
        send_error(m, MODEM_ERR_RADIO, "radio refused the channel");
        return false;
    }
    m->channel_hz = hz;
    return true;
}

/*
 * Flood copies of one packet arrive several times (direct and relayed).
 * Keyed on (source, epoch, seq) so a box that rebooted and restarted its
 * seq at 0 is not mistaken for a duplicate.
 */
static bool dedupe_seen(modem_t *m, uint16_t source, uint32_t nonce_ctr)
{
    uint32_t t = now(m);
    int free_slot = -1;
    int oldest = -1;
    uint32_t oldest_age = 0;
    for (int i = 0; i < MODEM_DEDUPE_SIZE; i++) {
        modem_dedupe_entry_t *e = &m->dedupe[i];
        if (e->used && t - e->seen_ms > MODEM_DEDUPE_EXPIRY_MS) {
            e->used = false;
        }
        if (!e->used) {
            if (free_slot < 0) free_slot = i;
            continue;
        }
        if (e->source == source && e->nonce_ctr == nonce_ctr) {
            return true;
        }
        uint32_t age = t - e->seen_ms;
        if (oldest < 0 || age > oldest_age) {
            oldest = i;
            oldest_age = age;
        }
    }
    /* Full table: evict the oldest entry (LRU), as core/src/flood.c does. */
    int slot = free_slot >= 0 ? free_slot : oldest;
    m->dedupe[slot].source = source;
    m->dedupe[slot].nonce_ctr = nonce_ctr;
    m->dedupe[slot].seen_ms = t;
    m->dedupe[slot].used = true;
    return false;
}

/* ---- Commands ------------------------------------------------------------- */

static bool cmd_configure(modem_t *m, const uint8_t *p, size_t len)
{
    if (len != MODEM_CONFIGURE_LEN) {
        send_error(m, MODEM_ERR_BAD_FRAME, "CONFIGURE needs 27 bytes of parameters");
        return false;
    }
    uint16_t game_id = be16(p + 1);
    uint16_t node_id = be16(p + 3);
    uint16_t epoch = be16(p + 5);
    uint8_t max_hops = p[7];
    uint32_t channel = be32(p + 8);
    const uint8_t *key = p + 12;
    if (max_hops > MODEM_MAX_HOPS) {
        send_error(m, MODEM_ERR_BAD_PARAMS, "max_hops above 3");
        return false;
    }
    if (!apply_channel(m, channel)) {
        return false;
    }
    bool same_game = m->configured && m->game_id == game_id && memcmp(m->rx.game_key, key, 16) == 0;
    if (!same_game) {
        /* A new game: forget every source epoch and every packet seen. */
        atalaia_radio_proto_init(&m->rx, game_id, node_id, m->crypto, NULL);
        atalaia_radio_proto_set_key(&m->rx, key);
        memset(m->dedupe, 0, sizeof(m->dedupe));
        m->tx_used = false;
        m->last_tx_nonce = 0;
    } else {
        m->rx.node_id = node_id;
    }
    /* The controller restarts its seq at 0 with a new epoch; a lower epoch
     * than the last one used would reuse nonces, so it is refused at TX. */
    m->game_id = game_id;
    m->node_id = node_id;
    m->tx_epoch = epoch;
    m->max_hops = max_hops;
    m->configured = true;
    return true;
}

static bool cmd_set_peer_epoch(modem_t *m, const uint8_t *p, size_t len)
{
    if (!m->configured) {
        send_error(m, MODEM_ERR_NOT_CONFIGURED, "SET_PEER_EPOCH needs CONFIGURE first");
        return false;
    }
    if ((len - 1) % 4 != 0) {
        send_error(m, MODEM_ERR_BAD_FRAME, "SET_PEER_EPOCH needs (source, epoch) pairs");
        return false;
    }
    for (size_t i = 1; i + 4 <= len; i += 4) {
        atalaia_radio_proto_set_source_epoch(&m->rx, be16(p + i), be16(p + i + 2));
    }
    return true;
}

/* MEASURE: noise on a channel, only while no game is configured (measuring
 * takes the radio off the game channel). Answered later by NOISE. Every
 * error message starts with "MEASURE" so the host can match it. */
static void cmd_measure(modem_t *m, const uint8_t *p, size_t len)
{
    if (len != MODEM_MEASURE_LEN) {
        send_error(m, MODEM_ERR_BAD_FRAME, "MEASURE needs 7 bytes of parameters");
        return;
    }
    uint32_t hz = be32(p + 1);
    uint16_t dwell = be16(p + 5);
    bool cad = (p[7] & MODEM_MEASURE_CAD) != 0;
    if (!m->radio_present || m->io.measure_start == NULL) {
        send_error(m, MODEM_ERR_NO_RADIO, "MEASURE: no radio to measure with");
        return;
    }
    if (m->configured) {
        send_error(m, MODEM_ERR_BUSY, "MEASURE: a game is configured; CLEAR it first");
        return;
    }
    if (m->measuring) {
        send_error(m, MODEM_ERR_BUSY, "MEASURE: a measurement is already running");
        return;
    }
    if (!atalaia_channel_ok(hz)) {
        send_error(m, MODEM_ERR_BAD_PARAMS, "MEASURE: channel does not fit in an EU868 sub-band");
        return;
    }
    if (dwell < NOISE_DWELL_MIN_MS || dwell > NOISE_DWELL_MAX_MS) {
        send_error(m, MODEM_ERR_BAD_PARAMS, "MEASURE: dwell must be 10-10000 ms");
        return;
    }
    if (m->io.measure_start(m->io.ctx, hz, dwell, cad) != 0) {
        send_error(m, MODEM_ERR_BUSY, "MEASURE: the radio is busy");
        return;
    }
    m->measuring = true;
}

void modem_on_measure_result(modem_t *m, int rc, const noise_result_t *r)
{
    if (!m->measuring) return;
    m->measuring = false;
    if (rc == 0 && r != NULL) {
        uint8_t buf[NOISE_RESULT_LEN];
        size_t n = noise_result_encode(r, buf, sizeof(buf));
        send_frame(m, MODEM_FRAME_NOISE, buf, n);
    } else if (rc == -2) {
        send_error(m, MODEM_ERR_BAD_PARAMS, "MEASURE: the radio refused the channel");
    } else {
        send_error(m, MODEM_ERR_RADIO, "MEASURE: the radio failed while measuring");
    }
}

static void handle_cmd(modem_t *m, const uint8_t *p, size_t len)
{
    if (len < 1) {
        send_error(m, MODEM_ERR_BAD_FRAME, "empty CMD");
        return;
    }
    m->count.cmds++;
    uint8_t op = p[0];
    switch (op) {
    case MODEM_CMD_PING:
        if (len == 5) {
            send_status(m, op, true, be32(p + 1));
        } else {
            send_status(m, op, false, 0);
        }
        return;
    case MODEM_CMD_CONFIGURE:
        if (m->measuring) {
            send_error(m, MODEM_ERR_BUSY, "CONFIGURE: a measurement is running");
            return;
        }
        if (!cmd_configure(m, p, len)) return;
        break;
    case MODEM_CMD_SET_CHANNEL:
        if (m->measuring) {
            send_error(m, MODEM_ERR_BUSY, "SET_CHANNEL: a measurement is running");
            return;
        }
        if (len != 5) {
            send_error(m, MODEM_ERR_BAD_FRAME, "SET_CHANNEL needs 4 bytes");
            return;
        }
        if (!apply_channel(m, be32(p + 1))) return;
        break;
    case MODEM_CMD_STATUS: break;
    case MODEM_CMD_SET_PEER_EPOCH:
        if (!cmd_set_peer_epoch(m, p, len)) return;
        break;
    case MODEM_CMD_CLEAR:
        memset(&m->rx, 0, sizeof(m->rx));
        memset(m->dedupe, 0, sizeof(m->dedupe));
        m->configured = false;
        m->game_id = 0;
        m->tx_used = false;
        m->last_tx_nonce = 0;
        break;
    case MODEM_CMD_IDENT: modem_send_ident(m); return;
    case MODEM_CMD_MEASURE: cmd_measure(m, p, len); return;
    default: send_error(m, MODEM_ERR_UNKNOWN_CMD, "unknown CMD opcode"); return;
    }
    send_status(m, op, false, 0);
}

/* ---- TX: host -> radio ---------------------------------------------------- */

static void handle_tx(modem_t *m, const uint8_t *p, size_t len)
{
    if (len < ATALAIA_RF_HEADER_SIZE) {
        send_error(m, MODEM_ERR_BAD_FRAME, "TX shorter than a header");
        return;
    }
    atalaia_header_t hdr;
    uint16_t seq = be16(p + 5);
    if (!atalaia_header_decode(p, &hdr)) {
        send_tx_ack(m, seq, MODEM_TX_INVALID);
        return;
    }
    if (!m->radio_present) {
        send_tx_ack(m, seq, MODEM_TX_NO_RADIO);
        return;
    }
    if (!m->configured) {
        send_tx_ack(m, seq, MODEM_TX_NOT_CONFIGURED);
        return;
    }
    size_t payload_len = len - ATALAIA_RF_HEADER_SIZE;
    if (payload_len > ATALAIA_RF_PAYLOAD_MAX || hdr.game_id != m->game_id ||
        hdr.source != m->node_id || ATALAIA_VF_VERSION(hdr.version_flags) != 1) {
        send_tx_ack(m, seq, MODEM_TX_INVALID);
        return;
    }
    uint32_t nonce_ctr = ((uint32_t)m->tx_epoch << 16) | hdr.seq;
    if (m->tx_used && nonce_ctr <= m->last_tx_nonce) {
        send_tx_ack(m, seq, MODEM_TX_NONCE_REUSE);
        return;
    }
    /* Always encrypted on LoRa; the relay clamp also applies to our own packets. */
    hdr.version_flags |= ATALAIA_VF_MAKE(0, 0, 0, 1);
    hdr.version_flags &= (uint8_t)~0x01u;
    if (hdr.hop_limit > m->max_hops) hdr.hop_limit = m->max_hops;

    uint8_t pkt[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE];
    size_t pkt_len =
        atalaia_packet_encrypt(&hdr, m->tx_epoch, m->rx.game_key, p + ATALAIA_RF_HEADER_SIZE,
                               payload_len, pkt, sizeof(pkt), m->crypto);
    if (pkt_len == 0) {
        send_tx_ack(m, seq, MODEM_TX_INVALID);
        return;
    }
    /* The nonce is spent once the packet is queued, whatever happens on air. */
    m->tx_used = true;
    m->last_tx_nonce = nonce_ctr;
    if (m->io.radio_send == NULL ||
        !m->io.radio_send(m->io.ctx, pkt, pkt_len, (uint32_t)hdr.seq + 1u)) {
        m->count.tx_fail++;
        send_tx_ack(m, seq, MODEM_TX_QUEUE_FULL);
    }
}

/* ---- Field frames: host <-> radio, as they are (protocol/field-frames.md) ---- */

static void send_field_ack(modem_t *m, uint16_t id, modem_tx_status_t status)
{
    uint8_t buf[3] = {(uint8_t)(id >> 8), (uint8_t)(id & 0xFF), (uint8_t)status};
    send_frame(m, MODEM_FRAME_FIELD_ACK, buf, sizeof(buf));
}

/* The shape of a field frame: version 1, encrypted, game 0, type FIELD, 31-217 bytes. The
 * modem cannot check more: the key is the field's, which only the controllers and boxes hold. */
static bool field_frame_shape(const uint8_t *pkt, size_t len)
{
    atalaia_header_t h;
    if (len < MODEM_FIELD_MIN || len > MODEM_FIELD_MAX || !atalaia_header_decode(pkt, &h)) {
        return false;
    }
    return h.game_id == 0 && h.type == ATALAIA_MSG_FIELD && ATALAIA_VF_ENC(h.version_flags);
}

static void handle_field_tx(modem_t *m, const uint8_t *p, size_t len)
{
    if (len < 2) {
        send_error(m, MODEM_ERR_BAD_FRAME, "FIELD_TX shorter than its id");
        return;
    }
    uint16_t id = be16(p);
    const uint8_t *frame = p + 2;
    size_t n = len - 2;
    if (!m->radio_present) {
        send_field_ack(m, id, MODEM_TX_NO_RADIO);
        return;
    }
    if (m->measuring) {
        send_field_ack(m, id, MODEM_TX_BUSY);
        return;
    }
    if (!field_frame_shape(frame, n)) {
        send_field_ack(m, id, MODEM_TX_INVALID);
        return;
    }
    /* Never relayed: hop_limit 0 (it is outside the AAD, so the MIC still holds). */
    uint8_t pkt[MODEM_FIELD_MAX];
    memcpy(pkt, frame, n);
    pkt[ATALAIA_RF_HOP_LIMIT_OFFSET] = 0;
    if (m->io.radio_send == NULL || !m->io.radio_send(m->io.ctx, pkt, n, MODEM_FIELD_TAG | id)) {
        m->count.tx_fail++;
        send_field_ack(m, id, MODEM_TX_QUEUE_FULL);
        return;
    }
    m->count.field_tx++;
}

void modem_on_tx_result(modem_t *m, uint32_t tag, modem_tx_status_t status)
{
    if (tag == 0) return;
    if (status == MODEM_TX_OK) {
        m->count.tx_ok++;
    } else {
        m->count.tx_fail++;
    }
    if (tag & MODEM_FIELD_TAG) {
        send_field_ack(m, (uint16_t)(tag & 0xFFFFu), status);
        return;
    }
    send_tx_ack(m, (uint16_t)(tag - 1u), status);
}

/* ---- RX: radio -> host ---------------------------------------------------- */

void modem_on_air_rx(modem_t *m, const uint8_t *pkt, size_t len, int8_t rssi, int8_t snr)
{
    /* A field frame: to the host as it is, with or without a game configured. */
    if (field_frame_shape(pkt, len)) {
        uint8_t frame[MODEM_FIELD_MAX + 2];
        memcpy(frame, pkt, len);
        frame[len] = (uint8_t)rssi;
        frame[len + 1] = (uint8_t)snr;
        m->count.field_rx++;
        send_frame(m, MODEM_FRAME_FIELD_RX, frame, len + 2);
        return;
    }
    if (!m->configured || len < ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE ||
        len > RADIO_MAX_PKT_LEN) {
        m->count.rx_dropped++;
        return;
    }
    atalaia_header_t hdr;
    if (!atalaia_header_decode(pkt, &hdr) || hdr.game_id != m->game_id ||
        !ATALAIA_VF_ENC(hdr.version_flags) || hdr.source == m->node_id) {
        /* Another game, unencrypted, or our own packet relayed back. */
        m->count.rx_dropped++;
        return;
    }

    radio_rx_msg_t msg;
    memcpy(msg.data, pkt, len);
    msg.len = len;
    msg.rssi = rssi;
    msg.timestamp_ms = now(m);

    uint8_t plain[ATALAIA_RF_PAYLOAD_MAX];
    size_t plain_len = 0;
    uint16_t epoch = 0;
    atalaia_header_t out_hdr;
    if (!atalaia_radio_proto_on_recv_window(&m->rx, &msg, m->epoch_window, &out_hdr, plain,
                                            &plain_len, &epoch)) {
        m->count.rx_auth_fail++;
        return;
    }
    if (dedupe_seen(m, hdr.source, ((uint32_t)epoch << 16) | hdr.seq)) {
        m->count.rx_dupes++;
        return;
    }

    /* RX payload: header (as received) + plaintext + rssi + snr + epoch. */
    uint8_t frame[ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + 4];
    memcpy(frame, pkt, ATALAIA_RF_HEADER_SIZE);
    memcpy(frame + ATALAIA_RF_HEADER_SIZE, plain, plain_len);
    size_t n = ATALAIA_RF_HEADER_SIZE + plain_len;
    frame[n++] = (uint8_t)rssi;
    frame[n++] = (uint8_t)snr;
    frame[n++] = (uint8_t)(epoch >> 8);
    frame[n++] = (uint8_t)(epoch & 0xFF);
    m->count.rx_ok++;
    send_frame(m, MODEM_FRAME_RX, frame, n);
}

/* ---- Frames from the host ------------------------------------------------- */

void modem_handle_frame(modem_t *m, uint8_t type, const uint8_t *payload, size_t len)
{
    /* Any whole frame (its CRC checked) shows the host is there. */
    m->host_seen = true;
    m->last_host_ms = now(m);
    switch (type) {
    case MODEM_FRAME_TX: handle_tx(m, payload, len); break;
    case MODEM_FRAME_CMD: handle_cmd(m, payload, len); break;
    case MODEM_FRAME_FIELD_TX: handle_field_tx(m, payload, len); break;
    default: send_error(m, MODEM_ERR_UNKNOWN_TYPE, "frame type not accepted by the modem"); break;
    }
}

static void on_frame(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    modem_handle_frame((modem_t *)ctx, type, payload, len);
}

void modem_feed_serial(modem_t *m, const uint8_t *data, size_t len)
{
    modem_decoder_feed(&m->dec, data, len, on_frame, m);
}

void modem_init(modem_t *m, const modem_io_t *io, const atalaia_crypto_ops_t *crypto,
                const char *fw_version, bool radio_present, uint16_t epoch_window)
{
    memset(m, 0, sizeof(*m));
    m->io = *io;
    m->crypto = crypto;
    m->fw_version = fw_version;
    m->radio_present = radio_present;
    m->epoch_window = epoch_window == 0 ? 1 : epoch_window;
    modem_decoder_init(&m->dec);
    m->boot_ms = now(m);
}
