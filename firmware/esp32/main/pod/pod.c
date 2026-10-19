/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's capability proxy. See pod.h and protocol/capability-proxy.md.
 */
#include "pod.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static void say(pod_t *p, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(pod_t *p, const char *fmt, ...)
{
    if (p->io.log == NULL) return;
    char line[128];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    p->io.log(p->io.ctx, line);
}

static uint32_t now(const pod_t *p)
{
    return p->io.now_ms != NULL ? p->io.now_ms(p->io.ctx) : 0;
}

static bool valid_link(int link)
{
    return link >= 0 && link < POD_LINK_COUNT;
}

/* ---- Output -------------------------------------------------------------------- */

static void write_frame(pod_t *p, int link, const uint8_t *frame, size_t len)
{
    if (!valid_link(link) || p->io.link_write == NULL) return;
    p->io.link_write(p->io.ctx, (pod_link_t)link, frame, len);
}

static void send(pod_t *p, int link, uint8_t type, const uint8_t *payload, size_t len)
{
    uint8_t frame[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(type, payload, len, frame, sizeof(frame));
    if (n > 0) write_frame(p, link, frame, n);
}

static void send_ack(pod_t *p, int link, uint16_t seq)
{
    uint8_t buf[2];
    size_t n = atalaia_proxy_ack_encode(seq, buf, sizeof(buf));
    send(p, link, ATALAIA_PROXY_ACK, buf, n);
}

void pod_send_ident(pod_t *p, pod_link_t link)
{
    atalaia_proxy_ident_t id;
    uint8_t buf[ATALAIA_PROXY_PAYLOAD_MAX];
    size_t n = 0;
    for (int compact = 0; compact < 2 && n == 0; compact++) {
        memset(&id, 0, sizeof(id));
        snprintf(id.caps_json, sizeof(id.caps_json), "[]");
        if (p->io.ident != NULL) p->io.ident(p->io.ctx, &id, compact != 0);
        id.has_radio = p->radio.radio_present;
        id.protocol_version = ATALAIA_PROXY_VERSION;
        n = atalaia_proxy_ident_encode(&id, buf, sizeof(buf));
    }
    if (n == 0) {
        /* Too many capabilities for 256 bytes (pod_caps keeps within it): say
         * who we are without them rather than not at all. */
        say(p, "IDENT does not fit; sent without capabilities");
        snprintf(id.caps_json, sizeof(id.caps_json), "[]");
        n = atalaia_proxy_ident_encode(&id, buf, sizeof(buf));
    }
    if (n > 0) send(p, (int)link, ATALAIA_PROXY_IDENT, buf, n);
}

/* ---- The radio: the modem's frames, 3 types up ------------------------------------- */

static void radio_out(void *ctx, uint8_t type, const uint8_t *payload, size_t len)
{
    pod_t *p = (pod_t *)ctx;
    if (p->muted || type == MODEM_FRAME_IDENT) return; /* RADIO_CMD IDENT gets the pod's IDENT */
    if (type < MODEM_FRAME_RX || type > MODEM_FRAME_NOISE) return;
    /* A reply goes back where its frame came from; a received packet, a TX
     * outcome or a measurement to the link that runs the radio. */
    int link = p->replying;
    if (!valid_link(link)) {
        link = valid_link(p->radio_owner) ? p->radio_owner : p->radio_link;
    }
    if (!valid_link(link) || !p->links[link].active) return;
    send(p, link, (uint8_t)(type + 3), payload, len);
}

static void radio_clear(pod_t *p, const char *why)
{
    if (!p->radio.configured && p->radio_owner < 0) return;
    const uint8_t clear = MODEM_CMD_CLEAR;
    int replying = p->replying;
    p->muted = true;
    p->replying = -1;
    modem_handle_frame(&p->radio, MODEM_FRAME_CMD, &clear, 1);
    p->muted = false;
    p->replying = replying;
    p->radio_owner = -1;
    p->count.radio_cleared++;
    say(p, "radio cleared: %s", why);
}

static void handle_radio(pod_t *p, int link, uint8_t type, const uint8_t *pl, size_t len)
{
    p->radio_link = link;
    if (type == ATALAIA_PROXY_RADIO_CMD && len >= 1 && pl[0] == MODEM_CMD_IDENT) {
        /* The phone's first frame on every new link: it numbers its CMDs from 0 again. */
        p->links[link].seen_count = 0;
        p->links[link].seen_next = 0;
        pod_send_ident(p, (pod_link_t)link);
        return;
    }
    uint8_t mtype = atalaia_proxy_modem_type(type);
    modem_handle_frame(&p->radio, mtype, pl, len);
    if (type == ATALAIA_PROXY_RADIO_CMD && len >= 1) {
        if (pl[0] == MODEM_CMD_CONFIGURE && p->radio.configured) p->radio_owner = link;
        if (pl[0] == MODEM_CMD_CLEAR) p->radio_owner = -1;
    }
}

/* ---- Frames from the phone ------------------------------------------------------- */

static bool seen_before(pod_link_state_t *l, uint16_t seq)
{
    for (uint8_t i = 0; i < l->seen_count; i++) {
        if (l->seen[i] == seq) return true;
    }
    l->seen[l->seen_next] = seq;
    l->seen_next = (uint8_t)((l->seen_next + 1) % POD_SEEN);
    if (l->seen_count < POD_SEEN) l->seen_count++;
    return false;
}

static void handle_cmd(pod_t *p, int link, const uint8_t *pl, size_t len)
{
    atalaia_proxy_msg_t m;
    if (!atalaia_proxy_msg_decode(pl, len, &m)) {
        p->count.bad_payloads++; /* not acknowledged: the phone sends it again */
        return;
    }
    send_ack(p, link, m.seq);
    if (seen_before(&p->links[link], m.seq)) {
        p->count.cmd_repeats++;
        return;
    }
    p->count.cmds++;
    if (p->io.command == NULL || !p->io.command(p->io.ctx, &m)) {
        p->count.cmd_unknown++;
        say(p, "CMD %s.%s: no such capability or method", m.cap_id, m.name);
    }
}

static void handle_ack(pod_t *p, const uint8_t *pl, size_t len)
{
    uint16_t seq;
    if (!atalaia_proxy_ack_decode(pl, len, &seq)) {
        p->count.bad_payloads++;
        return;
    }
    for (size_t i = 0; i < POD_OUTBOX; i++) {
        pod_pending_t *e = &p->outbox[i];
        if (e->used && e->seq == seq) {
            e->used = false;
            p->count.evt_acked++;
            return;
        }
    }
}

static void on_frame(void *ctx, uint8_t type, const uint8_t *pl, size_t len)
{
    pod_t *p = (pod_t *)ctx;
    int link = p->replying;
    if (!valid_link(link)) return;
    /* Any valid frame says the phone is on this link. */
    if (!p->links[link].active) pod_set_link_active(p, (pod_link_t)link);
    switch (type) {
    case ATALAIA_PROXY_CMD: handle_cmd(p, link, pl, len); break;
    case ATALAIA_PROXY_ACK: handle_ack(p, pl, len); break;
    case ATALAIA_PROXY_RADIO_TX:
    case ATALAIA_PROXY_RADIO_CMD: handle_radio(p, link, type, pl, len); break;
    default:
        /* IDENT, EVT and the radio's answers go the other way; unknown types
         * may come from a later version: counted, not answered. */
        p->count.ignored++;
        break;
    }
}

void pod_feed(pod_t *p, pod_link_t link, const uint8_t *data, size_t len)
{
    if (!valid_link((int)link)) return;
    int replying = p->replying;
    p->replying = (int)link;
    modem_decoder_feed(&p->links[link].dec, data, len, on_frame, p);
    p->replying = replying;
}

/* ---- Links ------------------------------------------------------------------------- */

static bool any_active(const pod_t *p)
{
    for (int i = 0; i < POD_LINK_COUNT; i++) {
        if (p->links[i].active) return true;
    }
    return false;
}

static void drop_outbox(pod_t *p)
{
    for (size_t i = 0; i < POD_OUTBOX; i++) {
        if (p->outbox[i].used) p->count.evt_lost++;
        p->outbox[i].used = false;
    }
}

static void deactivate(pod_t *p, int link, const char *why)
{
    pod_link_state_t *l = &p->links[link];
    l->active = false;
    if (p->radio_owner == link) radio_clear(p, why);
    if (p->radio_link == link) p->radio_link = -1;
    if (!any_active(p)) drop_outbox(p);
}

void pod_set_link_up(pod_t *p, pod_link_t link, bool up)
{
    if (!valid_link((int)link)) return;
    pod_link_state_t *l = &p->links[link];
    if (l->up == up) return;
    l->up = up;
    modem_decoder_init(&l->dec);
    l->seen_count = 0;
    l->seen_next = 0;
    if (!up) {
        deactivate(p, (int)link, link == POD_LINK_USB ? "USB host gone" : "Bluetooth link lost");
    }
}

void pod_set_link_active(pod_t *p, pod_link_t link)
{
    if (!valid_link((int)link)) return;
    pod_link_state_t *l = &p->links[link];
    if (l->active) return;
    l->up = true;
    l->active = true;
    if (p->io.link_active != NULL) p->io.link_active(p->io.ctx, link);
}

bool pod_link_active(const pod_t *p, pod_link_t link)
{
    return valid_link((int)link) && p->links[link].active;
}

/* ---- Events ------------------------------------------------------------------------ */

static void send_to_active(pod_t *p, const uint8_t *frame, size_t len)
{
    for (int i = 0; i < POD_LINK_COUNT; i++) {
        if (p->links[i].active) write_frame(p, i, frame, len);
    }
}

bool pod_event(pod_t *p, const char *cap_id, const char *event, const char *data_json)
{
    if (!any_active(p)) {
        p->count.evt_dropped++;
        return false;
    }
    pod_pending_t *slot = NULL;
    for (size_t i = 0; i < POD_OUTBOX && slot == NULL; i++) {
        if (!p->outbox[i].used) slot = &p->outbox[i];
    }
    if (slot == NULL) {
        p->count.evt_dropped++;
        say(p, "EVT %s.%s dropped: %d EVTs wait for their ACK", cap_id, event, POD_OUTBOX);
        return false;
    }
    atalaia_proxy_msg_t m;
    memset(&m, 0, sizeof(m));
    snprintf(m.cap_id, sizeof(m.cap_id), "%s", cap_id);
    snprintf(m.name, sizeof(m.name), "%s", event);
    snprintf(m.data_json, sizeof(m.data_json), "%s", data_json != NULL ? data_json : "");
    m.seq = p->evt_seq;
    uint8_t payload[ATALAIA_PROXY_PAYLOAD_MAX];
    size_t n = atalaia_proxy_msg_encode(&m, payload, sizeof(payload));
    size_t f =
        n > 0 ? modem_frame_encode(ATALAIA_PROXY_EVT, payload, n, slot->frame, sizeof(slot->frame))
              : 0;
    if (f == 0) {
        p->count.evt_dropped++;
        say(p, "EVT %s.%s does not encode", cap_id, event);
        return false;
    }
    p->evt_seq++;
    slot->used = true;
    slot->seq = m.seq;
    slot->tries = 0;
    slot->sent_ms = now(p);
    slot->len = (uint16_t)f;
    p->count.evt_sent++;
    send_to_active(p, slot->frame, f);
    return true;
}

void pod_tick(pod_t *p)
{
    uint32_t t = now(p);
    bool broken = false;
    for (size_t i = 0; i < POD_OUTBOX && !broken; i++) {
        pod_pending_t *e = &p->outbox[i];
        if (!e->used || t - e->sent_ms < POD_RETRY_MS) continue;
        if (e->tries >= POD_RETRIES) {
            broken = true;
            break;
        }
        e->tries++;
        e->sent_ms = t;
        p->count.evt_retries++;
        send_to_active(p, e->frame, e->len);
    }
    if (!broken) return;
    /* Nobody acknowledged an EVT sent 4 times: the phone is gone or stuck.
     * The links stay up; they become active again when the phone speaks. */
    say(p, "no ACK after %d resends: links broken", POD_RETRIES);
    for (int i = 0; i < POD_LINK_COUNT; i++) {
        if (p->links[i].active) {
            p->count.links_broken++;
            deactivate(p, i, "no ACK from the phone");
        }
    }
    drop_outbox(p);
}

size_t pod_pending(const pod_t *p)
{
    size_t n = 0;
    for (size_t i = 0; i < POD_OUTBOX; i++) {
        if (p->outbox[i].used) n++;
    }
    return n;
}

/* ---- The radio's side -------------------------------------------------------------- */

void pod_on_air_rx(pod_t *p, const uint8_t *pkt, size_t len, int8_t rssi, int8_t snr)
{
    p->last_rssi = rssi;
    modem_on_air_rx(&p->radio, pkt, len, rssi, snr);
}

void pod_on_tx_result(pod_t *p, uint32_t tag, modem_tx_status_t status)
{
    modem_on_tx_result(&p->radio, tag, status);
}

void pod_on_measure_result(pod_t *p, int rc, const noise_result_t *r)
{
    modem_on_measure_result(&p->radio, rc, r);
}

void pod_status_bytes(const pod_t *p, int battery_pct, bool usb_host, uint8_t out[3])
{
    out[0] = battery_pct < 0 || battery_pct > 100 ? 0xFF : (uint8_t)battery_pct;
    out[1] = p->last_rssi == INT8_MIN ? 0x80 : (uint8_t)p->last_rssi;
    out[2] = (uint8_t)((p->radio.radio_present ? 0x01 : 0) | (p->radio.configured ? 0x02 : 0) |
                       (usb_host ? 0x04 : 0));
}

/* ---- Init -------------------------------------------------------------------------- */

void pod_init(pod_t *p, const pod_io_t *io, const modem_io_t *radio_io,
              const atalaia_crypto_ops_t *crypto, const char *fw_version, bool radio_present,
              uint16_t epoch_window)
{
    memset(p, 0, sizeof(*p));
    p->io = *io;
    p->radio_owner = -1;
    p->radio_link = -1;
    p->replying = -1;
    p->last_rssi = INT8_MIN;
    for (int i = 0; i < POD_LINK_COUNT; i++) modem_decoder_init(&p->links[i].dec);
    modem_io_t rio = *radio_io;
    rio.serial_write = NULL;
    rio.frame_out = radio_out;
    rio.frame_ctx = p;
    modem_init(&p->radio, &rio, crypto, fw_version, radio_present, epoch_window);
}
